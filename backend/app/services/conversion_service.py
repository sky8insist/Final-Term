import asyncio
import hashlib
import json
from copy import deepcopy

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services import notes_service, task_service
from app.services.course_service import _owned
from app.services.subject_service import get_subject

SELECT = 'id,subject_id,request_id,source_kind,source_material_id,source_artifact_id,source_wrong_answer_id,source_version,source_node_id,target,options,result_artifact_id,result_exam_id,result_href,created_at,source_title:snapshot->>title,warnings:snapshot->warnings,source_lecture:snapshot->content->>lectureId,source_blocks:snapshot->source->blockIds'


def rpc(name, params):
    try:
        return get_supabase_client().rpc(name, params).execute().data
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code in {'40001', '40P01'}:
            raise HTTPException(409, '转换请求冲突、来源已改变或任务已取消，请重新读取') from exc
        if code in {'42501', '23503'}:
            raise HTTPException(404, '学习来源或转换任务不存在') from exc
        if code in {'22023', '22P02', '23514'}:
            raise HTTPException(422, '转换来源或生成结果无效') from exc
        raise


def fingerprint(payload) -> str:
    values = payload.model_dump(mode='json', by_alias=True, exclude={'request_id'})
    # Preserve fingerprints issued before optional selected-block support.
    if values['source'].get('blockIds') is None:
        values['source'].pop('blockIds',None)
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _question_source(*, user_id, subject_id, wrong_id):
    wrong = _owned(table='wrong_answers', row_id=wrong_id, user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    attempt = _owned(table='exam_attempts', row_id=wrong['attempt_id'], user_id=user_id, subject_id=subject_id)
    exam = _owned(table='exams', row_id=attempt['exam_id'], user_id=user_id, subject_id=subject_id)
    if exam.get('assessment_mode') == 'formal' and attempt['status'] != 'graded':
        raise HTTPException(409, '正式考试提交并完成评分后才能转换错题')
    question = _owned(table='questions', row_id=wrong['question_id'], user_id=user_id, subject_id=subject_id)
    links = client.table('exam_questions').select('question_version').eq('exam_id', exam['id']).eq('question_id', question['id']).limit(1).execute().data
    if not links:
        raise HTTPException(404, '题目不属于该次考试')
    versions = client.table('question_versions').select('stem,options,correct_answer,explanation,citations').eq('question_id', question['id']).eq('version', links[0]['question_version']).limit(1).execute().data
    responses = client.table('exam_responses').select('response').eq('user_id', user_id).eq('attempt_id', attempt['id']).eq('question_id', question['id']).limit(1).execute().data
    grades = client.table('grading_results').select('is_correct,error_type,feedback').eq('user_id', user_id).eq('attempt_id', attempt['id']).eq('question_id', question['id']).limit(1).execute().data
    if not versions or not responses or not grades or grades[0]['is_correct'] is not False:
        raise HTTPException(409, '需要已评分的错误作答记录')
    version = versions[0]
    return {'title': version['stem'][:300], 'content': {'questionId': question['id'], 'attemptId': attempt['id'],
        'question': version['stem'], 'options': version['options'], 'userAnswer': responses[0]['response'],
        'correctAnswer': version['correct_answer'], 'explanation': version['explanation'],
        'errorType': grades[0]['error_type'], 'feedback': grades[0]['feedback'], 'knowledgeKey': question['knowledge_key']},
        'citationIds': version['citations'], 'topicIds': [question['knowledge_point_id']] if question.get('knowledge_point_id') else []}


def snapshot_source(*, user_id, subject_id, source):
    source_id = str(source.id)
    warnings = []
    if source.kind == 'material':
        root = _owned(table='materials', row_id=source_id, user_id=user_id, subject_id=subject_id)
        if root['status'] != 'ready':
            raise HTTPException(409, '资料处理完成后才能转换')
        query=(get_supabase_client().table('content_blocks').select('id').eq('user_id',user_id)
               .eq('subject_id',subject_id).eq('material_id',source_id))
        selected=[str(value) for value in source.block_ids] if source.block_ids else None
        if selected:query=query.in_('id',selected)
        blocks=query.order('sequence_index').order('id').limit(31).execute().data
        if selected and {row['id'] for row in blocks}!=set(selected):
            raise HTTPException(404,'所选转录或内容块不属于该课程资料')
        if len(blocks) > 30:
            warnings.append('material_first_30_blocks')
        data = {'title': root['filename'], 'content': {'materialName': root['filename']},
                'citationIds': [row['id'] for row in blocks[:30]], 'topicIds': []}
    elif source.kind == 'wrong_answer':
        data = _question_source(user_id=user_id, subject_id=subject_id, wrong_id=source_id)
    else:
        root = _owned(table='artifacts', row_id=source_id, user_id=user_id, subject_id=subject_id)
        expected = 'notes' if source.kind == 'notes' else 'mind_map'
        if root['artifact_type'] != expected:
            raise HTTPException(404, '学习来源类型不匹配')
        if root['version'] != source.version:
            raise HTTPException(409, '来源已更新，请重新读取')
        bindings = (get_supabase_client().table('artifact_topics').select('knowledge_point_id')
                    .eq('user_id', user_id).eq('subject_id', subject_id).eq('artifact_id', source_id).execute().data)
        content = root['content']
        if source.kind == 'mind_map_node':
            content = next((row for row in content.get('nodes', []) if str(row['id']) == source.node_id), None)
            if content is None:
                raise HTTPException(404, '导图节点不存在')
            ids = content.get('sourceIds') or content.get('citationIds') or []
            title = content.get('label') or content.get('title') or root['title']
        else:
            ids = [value for section in content['sections'] for value in section['citationIds']]
            title = root['title']
        data = {'title': title, 'content': content, 'citationIds': ids,
                'topicIds': [row['knowledge_point_id'] for row in bindings]}
    citations = notes_service.canonical_sources(user_id=user_id, subject_id=subject_id,
        block_ids=notes_service.source_ids([{'id': value} for value in data['citationIds']]))
    if source.kind == 'mind_map_node':
        from app.services.mind_map_topic_service import learning
        overlay = learning(user_id=user_id, artifact_id=source_id)
        if overlay['artifactVersion'] != source.version:
            raise HTTPException(409, '导图已更新，请刷新后转换')
        topic_id = overlay['nodes'].get(source.node_id, {}).get('knowledgePointId')
        data['topicIds'] = [topic_id] if topic_id else []
    if source.kind=='material' and source.block_ids:
        # Only current explicit alignments are inherited, never stale text links.
        from app.services.lecture_service import selected_context
        aligned=selected_context(user_id=user_id,subject_id=subject_id,material_id=source_id,citations=citations)
        data['topicIds']=aligned['topicIds']
        data['content']['lectureId']=aligned['lectureId']
        data['content']['selectedBlockIds']=[row['id'] for row in citations]
        start=citations[0].get('startTime')
        data['title']=data['title'][:200]+(' · '+str(start)+'s' if start is not None else ' · 所选内容')
    if len(citations) > 30:
        raise HTTPException(422, '转换证据超过 30 个内容块，请缩小来源范围')
    return {'source': source.model_dump(mode='json', by_alias=True), 'title': data['title'],
            'content': deepcopy(data['content']), 'topicIds': data['topicIds'], 'citations': citations, 'warnings': warnings}


def serialize(row, *, user_id):
    snapshot = row.get('snapshot')
    row = {key: value for key, value in row.items() if key not in {'user_id', 'claim_token', 'snapshot', 'fingerprint'}}
    if snapshot:
        row.update(source_title=snapshot['title'], warnings=snapshot['warnings'])
        row.update(source_lecture=snapshot['content'].get('lectureId'),source_blocks=snapshot['source'].get('blockIds'))
    row['task'] = task_service.get_task(user_id=user_id, task_id=row['id'])
    row['source_href'] = source_href(row)
    return row


def source_href(row):
    if row.get('source_lecture'):
        from urllib.parse import urlencode
        return '/lectures?'+urlencode({'lectureId':row['source_lecture'],'blockId':(row.get('source_blocks') or [''])[0]})
    if row['source_kind'] == 'notes':
        return '/notes?noteId='+row['source_artifact_id']
    if row['source_kind'] == 'mind_map_node':
        from urllib.parse import urlencode
        return '/mind-map?'+urlencode({'artifactId':row['source_artifact_id'],'nodeId':row['source_node_id']})
    source_id = row.get('source_material_id') or row.get('source_wrong_answer_id')
    return '/convert?sourceKind='+row['source_kind']+'&sourceId='+str(source_id)


def get_conversion(*, user_id, conversion_id, subject_id=None, include_snapshot=False):
    rows = (get_supabase_client().table('learning_conversions').select('*' if include_snapshot else SELECT)
            .eq('user_id', user_id).eq('id', conversion_id).limit(1).execute().data)
    if not rows or (subject_id and rows[0]['subject_id'] != subject_id):
        raise HTTPException(404, '转换任务不存在')
    return rows[0] if include_snapshot else serialize(rows[0], user_id=user_id)


def enqueue(*, user_id, payload):
    subject_id = str(payload.subject_id)
    get_subject(user_id=user_id, subject_id=subject_id)
    existing = (get_supabase_client().table('learning_conversions').select('*').eq('user_id', user_id)
                .eq('request_id', str(payload.request_id)).limit(1).execute().data)
    digest = fingerprint(payload)
    if existing:
        if existing[0]['fingerprint'] != digest:
            raise HTTPException(409, '请求编号已用于不同的转换参数')
        return serialize(existing[0], user_id=user_id)
    snapshot = snapshot_source(user_id=user_id, subject_id=subject_id, source=payload.source)
    row = rpc('enqueue_conversion', {'p_user_id': user_id, 'p_subject_id': subject_id,
        'p_request_id': str(payload.request_id), 'p_fingerprint': digest,
        'p_source': payload.source.model_dump(mode='json', by_alias=True), 'p_target': payload.target,
        'p_options': {'count': payload.count, 'mode': payload.mode}, 'p_snapshot': snapshot})
    return serialize(row, user_id=user_id)


def list_conversions(*, user_id, subject_id, object_id=None):
    get_subject(user_id=user_id, subject_id=subject_id)
    query = get_supabase_client().table('learning_conversions').select(SELECT).eq('user_id', user_id).eq('subject_id', subject_id)
    if object_id:
        query = query.or_(f'source_material_id.eq.{object_id},source_artifact_id.eq.{object_id},source_wrong_answer_id.eq.{object_id},result_artifact_id.eq.{object_id},result_exam_id.eq.{object_id}')
    rows = query.order('created_at', desc=True).limit(30).execute().data
    # One bulk task read; no N+1 status requests in history.
    ids = [row['id'] for row in rows]
    tasks = (get_supabase_client().table('processing_tasks').select(task_service.TASK_SELECT).eq('user_id', user_id)
             .eq('subject_id', subject_id).in_('id', ids).execute().data) if ids else []
    by_id = {row['id']: task_service._serialize(row) for row in tasks}
    return [{**row, 'source_href': source_href(row), 'task': by_id[row['id']]} for row in rows if row['id'] in by_id]


def transition(*, user_id, conversion_id, action):
    row = rpc('transition_conversion', {'p_user_id': user_id, 'p_id': conversion_id, 'p_action': action})
    return task_service._serialize(row)


async def generate_draft(job):
    snapshot, options = job['snapshot'], job['options']
    context = {'citations': snapshot['citations'], 'noteContent': snapshot['content'], 'retrieval': {
        'externalUsed': False, 'sourceArtifactId': job.get('source_artifact_id'), 'sourceArtifactVersion': job.get('source_version')}}
    topic_id = snapshot['topicIds'][0] if len(snapshot['topicIds']) == 1 else None
    if job['target'] == 'tutor':
        return {}
    if job['target'] == 'notes':
        from app.models.notes import NoteGenerateRequest
        return await notes_service.generate_note(user_id=job['user_id'],
            payload=NoteGenerateRequest(subjectId=job['subject_id'], mode=options['mode'], scope=snapshot['title'][:1000],
                count=options['count'], knowledgePointId=topic_id), source_context=context, draft_only=True)
    if job['target'] == 'quiz':
        from app.models.exam import ExamGenerateRequest
        from app.services.exam_service import generate_exam
        payload = ExamGenerateRequest(subjectId=job['subject_id'], title=snapshot['title'][:280]+' · 测验',
            scope=snapshot['title'][:1000], durationMinutes=30, questionTypes=[{'questionType':'single_choice', 'count':options['count'], 'pointsEach':5}],
            assessmentType='practice', knowledgePolicy='course_only', knowledgePointId=topic_id)
        return await generate_exam(user_id=job['user_id'], payload=payload, source_context=context, draft_only=True)
    from app.services.artifact_service import generate_artifact
    return await generate_artifact(user_id=job['user_id'], subject_id=job['subject_id'], artifact_type=job['target'],
        scope=snapshot['title'][:1000], material_ids=None, mode='knowledge', count=options['count'],
        knowledge_point_id=topic_id, source_context=context, draft_only=True)


def run_conversion(conversion_id):
    job = rpc('claim_conversion', {'p_id': conversion_id})
    if not job:
        return None
    try:
        draft = asyncio.run(generate_draft(job))
        result = rpc('finish_conversion', {'p_id': conversion_id, 'p_token': job['claim_token'], 'p_draft': draft})
        return {'id': result['id'], 'status': 'succeeded', 'resultHref': result.get('result_href')}
    except Exception as exc:
        rpc('transition_conversion', {'p_user_id': job['user_id'], 'p_id': conversion_id,
            'p_action': 'fail', 'p_token': job['claim_token'], 'p_error': str(getattr(exc, 'detail', '转换生成失败，请重试'))})
        return {'id': conversion_id, 'status': 'not_published'}


def tutor_context(*, user_id, subject_id, conversion_id):
    job = get_conversion(user_id=user_id, conversion_id=conversion_id, subject_id=subject_id, include_snapshot=True)
    task = task_service.get_task(user_id=user_id, task_id=conversion_id)
    if job['target'] != 'tutor' or task['status'] != 'succeeded':
        raise HTTPException(409, 'Tutor 转换尚未完成')
    snapshot = job['snapshot']
    canonical = notes_service.canonical_sources(user_id=user_id, subject_id=subject_id,
        block_ids=[row['id'] for row in snapshot['citations']])
    if canonical != snapshot['citations']:
        raise HTTPException(409, '学习来源已经改变，请重新转换')
    return snapshot


def list_wrong_answers(*, user_id, subject_id):
    get_subject(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    rows = (client.table('wrong_answers').select('id,question_id,attempt_id,error_type,diagnosis,created_at')
        .eq('user_id', user_id).eq('subject_id', subject_id).order('created_at', desc=True).limit(30).execute().data)
    if not rows:
        return []
    attempts = client.table('exam_attempts').select('id,exam_id,status').eq('user_id', user_id).eq('subject_id', subject_id).in_('id', list({row['attempt_id'] for row in rows})).execute().data
    exams = client.table('exams').select('id,assessment_mode').eq('user_id', user_id).eq('subject_id', subject_id).in_('id', list({row['exam_id'] for row in attempts})).execute().data if attempts else []
    modes = {row['id']: row['assessment_mode'] for row in exams}
    allowed = {row['id'] for row in attempts if row['exam_id'] in modes and (modes[row['exam_id']] != 'formal' or row['status'] == 'graded')}
    questions = client.table('questions').select('id,knowledge_key').eq('user_id', user_id).eq('subject_id', subject_id).in_('id', list({row['question_id'] for row in rows})).execute().data
    names = {row['id']: row['knowledge_key'] for row in questions}
    return [{**row, 'title': names.get(row['question_id'], '错题')+' · '+(row['error_type'] or '待分析')}
        for row in rows if row['attempt_id'] in allowed]


def dispatch(conversion_id):
    try:
        from app.worker.tasks import process_conversion
        process_conversion.delay(conversion_id)
        return True
    except Exception:
        return False  # Durable queued task is picked up by Beat's outbox sweep.


def sweep():
    from datetime import UTC, datetime, timedelta
    client = get_supabase_client()
    cutoff = (datetime.now(UTC)-timedelta(minutes=20)).isoformat()
    rows = (client.table('processing_tasks').select('id').eq('task_type','learning_conversion')
            .or_(f'status.eq.queued,and(status.eq.running,started_at.lt.{cutoff})').order('created_at').limit(50).execute().data)
    return sum(dispatch(row['id']) for row in rows)
