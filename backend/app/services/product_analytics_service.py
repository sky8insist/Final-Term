"""Owned, persisted product evidence; never accepts client learning outcomes."""
from copy import deepcopy
from uuid import UUID, uuid4
import base64
import binascii
import json
from datetime import UTC, datetime

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.observability_service import current_trace_metadata
from app.services.study_signal_service import ALGORITHM_VERSION as SIGNAL_VERSION
from app.services.learner_state_service import STATE_VERSION


def deliver(*, user_id: str, result: dict) -> dict:
    result = deepcopy(result)
    rows = []
    for rank, action in enumerate(result["actions"], 1):
        audit_id = str(uuid4())
        snapshot = {**action, "rank": rank, "generatedAt": result["generatedAt"],
                    "algorithmVersions": {"recommendation": result["algorithmVersion"], "studySignal": SIGNAL_VERSION,
                                          "learnerState": STATE_VERSION},
                    "trace": current_trace_metadata()}
        rows.append({"id": audit_id, "user_id": user_id, "subject_id": action["subjectId"],
                     "knowledge_point_id": action.get("knowledgePointId"),
                     "algorithm_version": result["algorithmVersion"], "snapshot": snapshot})
        action["recommendationId"] = audit_id
        if action.get("knowledgePointId"):
            action["href"] += "&recommendationId=" + audit_id
    if rows:
        # Batch insert is atomic. Never return a tracking ID whose snapshot was not saved.
        get_supabase_client().table("recommendation_audits").insert(rows).execute()
    return result


def record_feedback(*, user_id: str, recommendation_id: str, event: str) -> dict:
    try:
        return get_supabase_client().rpc("record_recommendation_feedback", {
            "p_user": user_id, "p_recommendation": recommendation_id, "p_event": event,
        }).execute().data
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == "42501": raise HTTPException(404, "推荐记录不存在") from exc
        if code == "22023": raise HTTPException(409, "推荐已过期，请刷新建议") from exc
        raise


def _cursor(value: str, scope: str) -> tuple[str, str]:
    try:
        if len(value) > 1024: raise ValueError('Long cursor')
        decoded = json.loads(base64.b64decode(value + '='*(-len(value) % 4), altchars=b'-_', validate=True))
        if not isinstance(decoded, dict) or set(decoded) != {'v', 'scope', 'at', 'id'} or type(decoded['v']) is not int or decoded['v'] != 1 or decoded['scope'] != scope:
            raise ValueError('Cursor scope changed')
        if not isinstance(decoded['at'], str) or not isinstance(decoded['id'], str): raise ValueError('Cursor types changed')
        at = datetime.fromisoformat(decoded['at'])
        if at.tzinfo is None: raise ValueError('Timezone required')
        return at.astimezone(UTC).isoformat(), str(UUID(decoded['id']))
    except (ValueError, TypeError, KeyError, binascii.Error):
        raise HTTPException(422, '分页位置无效，请重新加载记录') from None


def _page(query, *, scope: str, cursor: str | None, limit: int) -> dict:
    if not 1 <= limit <= 100: raise HTTPException(422, '每页数量必须为 1–100')
    if cursor:
        at, row_id = _cursor(cursor, scope)
        query = query.or_(f'created_at.lt.{at},and(created_at.eq.{at},id.lt.{row_id})')
    rows = query.order('created_at', desc=True).order('id', desc=True).limit(limit+1).execute().data
    items, more = rows[:limit], len(rows) > limit
    next_cursor = None
    if more:
        last = items[-1]
        payload = {'v': 1, 'scope': scope, 'at': last['created_at'], 'id': last['id']}
        next_cursor = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    return {'items': items, 'hasMore': more, 'nextCursor': next_cursor}


def history(*, user_id: str, cursor: str | None = None, limit: int = 20) -> dict:
    query = get_supabase_client().table('recommendation_audits').select('*').eq('user_id', user_id)
    return _page(query, scope=f'history:{user_id}', cursor=cursor, limit=limit)


def audit(*, user_id: str, recommendation_id: str, cursor: str | None = None, limit: int = 100) -> dict:
    client = get_supabase_client()
    rows = (client.table("recommendation_audits").select("*").eq("user_id", user_id)
            .eq("id", recommendation_id).limit(1).execute().data)
    if not rows: raise HTTPException(404, "推荐记录不存在")
    query = (client.table("product_events").select("*").eq("user_id", user_id)
             .contains("payload", {"recommendationId": recommendation_id}))
    page = _page(query, scope=f'audit:{user_id}:{recommendation_id}', cursor=cursor, limit=limit)
    return {"recommendation": rows[0], "events": page['items'], "hasMore": page['hasMore'], 'nextCursor': page['nextCursor']}


def metrics(*, user_id: str, days: int) -> dict:
    return get_supabase_client().rpc("product_quality_metrics", {"p_user": user_id, "p_days": days}).execute().data


def learning_outcomes(*, user_id: str, days: int) -> dict:
    return get_supabase_client().rpc("learning_outcome_metrics", {"p_user": user_id, "p_days": days}).execute().data


def prediction_coverage(*, user_id: str, days: int) -> dict:
    return get_supabase_client().rpc('prediction_coverage_metrics', {'p_user': user_id, 'p_days': days}).execute().data
