"""Durable opt-in upload Notes. Generation/publication belongs to conversions."""
from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.models.conversion import ConversionRequest
from app.services import conversion_service
from app.services.course_service import _owned


def rpc(name, values):
    try:
        return get_supabase_client().rpc(name, values).execute().data
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == '42501': raise HTTPException(404, '资料不存在') from exc
        if code in {'40001', '40P01'}: raise HTTPException(409, '笔记配置或任务状态已变化，请刷新后重试') from exc
        if code == '22023': raise HTTPException(422, '资料尚未选择自动笔记或任务参数无效') from exc
        raise


def configure(*, user_id, material_id, mode):
    return rpc('configure_upload_notes', {'p_user': user_id, 'p_material': material_id, 'p_mode': mode})


def transition(user_id, material_id, action, conversion_id=None):
    return rpc('transition_upload_notes', {'p_user': user_id, 'p_material': material_id,
               'p_action': action, 'p_conversion': conversion_id})


def existing(mat):
    rows = (get_supabase_client().table('learning_conversions').select('id')
            .eq('user_id', mat['user_id']).eq('subject_id', mat['subject_id'])
            .eq('request_id', mat['upload_notes_request_id']).limit(1).execute().data)
    return rows[0]['id'] if rows else None


def enqueue_for_material(*, user_id, subject_id, material_id):
    mat = _owned(table='materials', row_id=material_id, user_id=user_id, subject_id=subject_id)
    if not mat.get('upload_notes_mode') or mat['status'] != 'ready' or mat.get('upload_notes_dispatched'):
        return None
    mat = transition(user_id, material_id, 'start')
    if mat is None:
        return None
    try:
        # Recover an enqueue-before-acknowledgement crash using the same request ID.
        payload = ConversionRequest(requestId=mat['upload_notes_request_id'], subjectId=subject_id,
            source={'kind': 'material', 'id': material_id}, target='notes', count=10,
            mode=mat['upload_notes_mode'])
        job = conversion_service.enqueue(user_id=user_id, payload=payload)
        transition(user_id, material_id, 'done', job['id'])
        conversion_service.dispatch(job['id'])  # Existing conversion outbox covers broker failure.
        return job
    except Exception:
        transition(user_id, material_id, 'error')
        raise


def sweep():
    rows = rpc('pending_upload_notes', {}) or []
    count = 0
    for row in rows:
        try:
            if enqueue_for_material(user_id=row['user_id'], subject_id=row['subject_id'], material_id=row['id']):
                count += 1
        except Exception:
            # A broken source must not block the remaining ready materials.
            continue
    return count


def retry(*, user_id, subject_id, material_id):
    mat = _owned(table='materials', row_id=material_id, user_id=user_id, subject_id=subject_id)
    if not mat.get('upload_notes_mode'):
        raise HTTPException(409, '该资料未选择自动笔记，请使用资料转换入口')
    conversion_id = existing(mat)
    if conversion_id:
        # Includes cancellation and exhausted-attempt checks from unified conversions.
        conversion_service.transition(user_id=user_id, conversion_id=conversion_id, action='retry')
        conversion_service.dispatch(conversion_id)
        return {'conversionId': conversion_id}
    if mat.get('upload_notes_dispatched'):
        raise HTTPException(409, '笔记结果或任务已删除，不会自动重新生成，请使用资料转换入口')
    transition(user_id, material_id, 'reset')
    job = enqueue_for_material(user_id=user_id, subject_id=subject_id, material_id=material_id)
    return {'conversionId': job['id'] if job else None}
