from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.learner_state_service import derive_state


def rpc(name, values):
    try: return get_supabase_client().rpc(name, values).execute().data
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == '42501': raise HTTPException(404, '导图不存在') from exc
        if code in {'40001', '40P01'}: raise HTTPException(409, '导图或节点关联已变化，请刷新后重试') from exc
        if code in {'22023', '23503'}: raise HTTPException(422, '节点或同科目知识点不可用') from exc
        raise


def learning(*, user_id, artifact_id):
    data = rpc('read_mind_map_learning', {'p_user': user_id, 'p_artifact': artifact_id})
    for row in data['nodes'].values():
        mastery = row.pop('mastery')
        if not row['knowledgePointId']:
            row.update(state='unbound', masteryScore=None, masteryConfidence=None, learnerConfidence=None,
                       lastReviewAt=None, nextReviewAt=None, misconceptionRisk=0, reasons=[])
            continue
        row.update(derive_state(mastery, covered=row.pop('covered')))
        row['lastReviewAt'] = (mastery or {}).get('last_reviewed_at')
        if not mastery or not mastery.get('attempts'):
            row['masteryScore'] = None
            row['masteryConfidence'] = None
    return data


def bind(*, user_id, artifact_id, node_id, topic_id, artifact_version, binding_version):
    return rpc('bind_mind_map_topic', {'p_user': user_id, 'p_artifact': artifact_id, 'p_node': node_id,
               'p_topic': topic_id, 'p_artifact_version': artifact_version, 'p_binding_version': binding_version})
