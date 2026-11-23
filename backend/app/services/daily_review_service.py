"""Deterministic learning closure graph; canonical rows are the only evidence."""
from datetime import datetime
from typing import TypedDict
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph

from app.db.supabase_client import get_supabase_client
from app.services.learner_state_service import derive_state
from app.services.subject_service import get_subject


class ReviewState(TypedDict, total=False):
    source: dict
    report: dict


def rpc(name: str, values: dict):
    try: return get_supabase_client().rpc(name, values).execute().data
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == '42501': raise HTTPException(404, '学习复盘或科目不存在') from exc
        if code in {'40001','23505','40P01'}: raise HTTPException(409, '学习记录或计划已变化，请重新生成复盘') from exc
        if code == '22023': raise HTTPException(422, '请复盘上海时区当天，并检查改期条件') from exc
        raise


def closure(state: ReviewState) -> dict:
    source = state['source']
    topics, changes = [], []
    for topic in source['topics']:
        mastery = topic['mastery']
        row = {'id':topic['id'],'title':topic['title'], **derive_state(mastery, covered=topic['covered'])}
        if not mastery or not mastery.get('attempts'):
            row['masteryScore'] = None
            row['masteryConfidence'] = None
        topics.append(row)
        if topic['lastEvidenceId']:
            before, after = topic['before'], topic['after']
            changes.append({'topicId':topic['id'],'title':topic['title'],'before':before,'after':after,
                'deltaPoints':round((after-before)*100,2) if before is not None else None,
                'evidenceId':topic['lastEvidenceId'], 'unit':'percentage_points'})
    unresolved = [row for row in topics if row['state']=='at_risk' or (row['masteryScore'] is not None and row['masteryScore']<.6)]
    unresolved.sort(key=lambda row:(row['state']!='at_risk',row['masteryScore'] if row['masteryScore'] is not None else 1,row['id']))
    return {'report': {'version':'daily-review-v1','day':source['day'],'timezone':source['timezone'],
        'todaySummary':{'completedTasks':source['completedTasks'],'submittedTodayGradedAttempts':source['submittedTodayGradedAttempts'],
                        'learningEvents':source['learningEvents']},
        'masteryChanges':changes,'unresolvedProblems':unresolved,'tomorrowTasks':source['tomorrowTasks'],
        'tomorrowExams':source['exams']}}


def planner(state: ReviewState) -> dict:
    source, report = state['source'], dict(state['report'])
    capacity, used = source['capacity'], source['usedMinutes']
    remaining = max(0, capacity-used) if capacity is not None else 0
    ranked = {row['id']:index for index,row in enumerate(report['unresolvedProblems'])}
    moves = []
    slots = set()
    candidates = sorted(source['candidates'],key=lambda row:(ranked.get(row['topicId'],9999),row['id']))
    for row in candidates:
        slot = row.get('slotKey',row['id'])
        if row['topicId'] not in ranked or row['minutes']>remaining or len(moves)>=3 or slot in slots: continue
        moves.append({'taskId':row['id'],'planId':row['planId'],'title':row['title'],'topicId':row['topicId'],
                      'minutes':row['minutes'],'from':row['from'],'reason':'薄弱或需巩固知识点的未完成自动任务'})
        remaining -= row['minutes']
        slots.add(slot)
    report.update(proposedMoves=moves,requiresConfirmation=bool(moves),
        tomorrowRecommendations=[{'topicId':row['id'],'title':row['title'],'reason':'需巩固' if row['state']=='at_risk' else '已评估掌握度偏低',
            'href':f"/guided-study?topicId={row['id']}"} for row in report['unresolvedProblems'][:3]])
    return {'report':report}


def critic(state: ReviewState) -> dict:
    source, report = state['source'], dict(state['report'])
    moves = report['proposedMoves']
    candidates = {row['id']:row for row in source['candidates']}
    if len({row['taskId'] for row in moves})!=len(moves): raise ValueError('Duplicate task proposal')
    for move in moves:
        row = candidates.get(move['taskId'])
        if not row or any(move[key]!=row[source_key] for key,source_key in [('planId','planId'),('topicId','topicId'),('minutes','minutes')]):
            raise ValueError('Unsupported proposal')
    capacity, used = source['capacity'], source['usedMinutes']
    proposed = sum(row['minutes'] for row in moves)
    if proposed and (capacity is None or used+proposed>capacity): raise ValueError('Capacity exceeded')
    warnings = []
    if capacity is None: warnings.append('明日可用时间尚未设置，仅展示建议，不自动改期。')
    elif used>capacity: warnings.append('明日现有任务已超出跨科目总预算，请先检查日历。')
    report['feasibility']={'capacityMinutes':capacity,'existingMinutes':used,'proposedMinutes':proposed,
        'withinBudget':used+proposed<=capacity if capacity is not None else None,'warnings':warnings,
        'scope':'all_active_plans','minutesMeaning':'task_budget_not_measured_time'}
    return {'report':report}


def build_learning_review_graph():
    graph = StateGraph(ReviewState)
    graph.add_node('closure',closure); graph.add_node('planning',planner); graph.add_node('critic',critic)
    graph.add_edge(START,'closure'); graph.add_edge('closure','planning'); graph.add_edge('planning','critic'); graph.add_edge('critic',END)
    return graph.compile()


def preview(*, user_id: str, subject_id: str) -> dict:
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    source = rpc('daily_learning_source',{'p_user':user_id,'p_subject':subject_id,'p_day':day})
    return build_learning_review_graph().invoke({'source':source})['report']


def create(*, user_id: str, subject_id: str, request_id: str) -> dict:
    client = get_supabase_client()
    rows = (client.table('daily_learning_reviews').select('id,subject_id,day,report,status,version,created_at,request_id')
            .eq('user_id',user_id).eq('request_id',request_id).limit(1).execute().data)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    if rows:
        if rows[0]['subject_id']!=subject_id: raise HTTPException(409,'请求编号已用于其他科目')
        return rows[0]
    source = rpc('daily_learning_source',{'p_user':user_id,'p_subject':subject_id,'p_day':day})
    report = build_learning_review_graph().invoke({'source':source})['report']
    return rpc('save_daily_learning_review',{'p_user':user_id,'p_subject':subject_id,'p_day':day,
        'p_request':request_id,'p_source':source,'p_report':report})


def get(*, user_id: str, review_id: str) -> dict:
    rows = (get_supabase_client().table('daily_learning_reviews').select('id,subject_id,day,report,status,version,created_at,request_id')
            .eq('user_id',user_id).eq('id',review_id).limit(1).execute().data)
    if not rows: raise HTTPException(404,'学习复盘不存在')
    return rows[0]


def history(*, user_id: str, subject_id: str, before: str | None = None, before_id: str | None = None) -> list[dict]:
    get_subject(user_id=user_id,subject_id=subject_id)
    query = (get_supabase_client().table('daily_learning_reviews').select('id,subject_id,day,report,status,version,created_at,request_id')
             .eq('user_id',user_id).eq('subject_id',subject_id))
    if before and before_id: query = query.or_(f'created_at.lt.{before},and(created_at.eq.{before},id.lt.{before_id})')
    elif before: query = query.lt('created_at',before)
    return query.order('created_at',desc=True).order('id',desc=True).limit(30).execute().data


def decide(*, user_id: str, review_id: str, version: int, approve: bool) -> dict:
    return rpc('decide_daily_learning_review',{'p_user':user_id,'p_review':review_id,'p_version':version,'p_approve':approve})
