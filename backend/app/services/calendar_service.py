import hashlib
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services import notes_service
from app.services.course_service import _owned
from app.services.subject_service import get_subject


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def rpc(name, values):
    try:
        return get_supabase_client().rpc(name, values).execute().data
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code in {'40001', '40P01'}: raise HTTPException(409, '日程已变化、任务受保护或时间不足，请刷新后重试') from exc
        if code in {'42501', '23503'}: raise HTTPException(404, '日程来源不存在') from exc
        if code in {'22023', '23514', '22P02'}: raise HTTPException(422, '请检查日期、考试范围，并先设置目标日可用时间') from exc
        raise


def calendar(*, user_id, start, end, subject_id=None):
    if not 0 <= (end-start).days <= 41: raise HTTPException(422, '一次最多查看 42 天')
    days = rpc('learning_calendar', {'p_user':user_id,'p_start':start.isoformat(),'p_end':end.isoformat(),'p_subject':subject_id})
    for day in days:
        day['overCapacity'] = day['minutes'] is not None and day['plannedMinutes'] > day['minutes']
        day['examConflict'] = day.get('globalExamCount',len(day['exams'])) > 1
        day['missedCount'] = sum(row['status'] in {'pending','overdue'} and day['date'] < today().isoformat() for row in day['tasks'])
    return {'timezone':'Asia/Shanghai','today':today().isoformat(),'days':days}


def save_availability(*, user_id, day, minutes, version):
    return rpc('save_calendar_availability', {'p_user':user_id,'p_day':day.isoformat(),'p_minutes':minutes,'p_version':version})


def move_task(*, user_id, task_id, day, version):
    return rpc('move_calendar_task', {'p_user':user_id,'p_task':task_id,'p_day':day.isoformat(),'p_version':version})


def extract_candidates(text):
    """Conservative date extraction; never infer a year or map chapter labels to Topics."""
    lines = text.splitlines()
    result = []
    for index, line in enumerate(lines):
        if not re.search(r'\b(?:final\s+exam|midterm(?:\s+exam)?|exam)\b|期末考试|期中考试|考试日期', line, re.I): continue
        for match in re.finditer(r'(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)',line):
            try: day = date(*map(int,match.groups()))
            except ValueError: continue
            if day < today() or day > today()+timedelta(days=730): continue
            title = line[:match.start()].strip(' :：-')[:300] or '考试'
            scope = '\n'.join(lines[index+1:index+3])[:1000]
            result.append({'title':title,'exam_date':day.isoformat(),'scope_text':scope})
    return result


def propose(*, user_id, subject_id, material_id):
    get_subject(user_id=user_id, subject_id=subject_id)
    material = _owned(table='materials',row_id=material_id,user_id=user_id,subject_id=subject_id)
    if material['status'] != 'ready': raise HTTPException(409, '大纲资料处理完成后才能提取')
    client = get_supabase_client()
    blocks = (client.table('content_blocks').select('id,content_text').eq('user_id',user_id).eq('subject_id',subject_id)
        .eq('material_id',material_id).order('sequence_index').order('id').limit(501).execute().data)
    candidates=[]
    # Keep following blocks as evidence when chapter scope follows the exam line.
    for index, block in enumerate(blocks[:500]):
        if len(candidates)>=20: break
        neighbors=blocks[index:min(index+3,500)]
        for proposal in extract_candidates(block['content_text']):
            if len(candidates)>=20: break
            if not proposal['scope_text']:
                proposal['scope_text']='\n'.join(row['content_text'] for row in neighbors[1:])[:1000]
            evidence=notes_service.canonical_sources(user_id=user_id,subject_id=subject_id,block_ids=sorted(row['id'] for row in neighbors))
            digest=hashlib.sha256(json.dumps([proposal,evidence],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            row={'user_id':user_id,'subject_id':subject_id,'material_id':material_id,'fingerprint':digest,**proposal,'evidence':evidence}
            client.table('calendar_exam_proposals').upsert(row,on_conflict='user_id,material_id,fingerprint',ignore_duplicates=True).execute()
            candidates.append(digest)
    rows=client.table('calendar_exam_proposals').select('id,title,exam_date,scope_text,evidence,event_id,fingerprint').eq('user_id',user_id).eq('subject_id',subject_id).eq('material_id',material_id).in_('fingerprint',candidates).order('created_at',desc=True).limit(20).execute().data if candidates else []
    return {'proposals':rows,'truncated':len(blocks)>500,'candidateCount':len(candidates),'warnings':['仅识别明确年份的考试日期；章节范围须人工映射知识点。']}


def confirm(*, user_id, proposal_id, values):
    return rpc('confirm_calendar_exam',{'p_user':user_id,'p_id':proposal_id,'p_values':values})
