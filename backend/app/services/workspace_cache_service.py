from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from fastapi import HTTPException

logger = logging.getLogger(__name__)

RESOURCE_TTLS = {
    "dashboard": 300,
    "subjects": 900,
    "chat": 86400,
    "mind-map": 86400,
    "exams": 900,
    "plan": 600,
    "workspace": 604800,
    "recommendations": 60,
}
MAX_SNAPSHOT_BYTES = 1_000_000


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.3,
        health_check_interval=30,
    )


def _key(*, user_id: str, resource: str, subject_id: str | None, version: str) -> str:
    scope = subject_id or "global"
    return f"workspace:v2:{user_id}:{resource}:{scope}:{version}"


def current_version(*,user_id: str,resource: str,subject_id: str | None = None) -> dict:
    if resource not in RESOURCE_TTLS:raise ValueError('Unsupported workspace cache resource')
    try:
        return get_supabase_client().rpc('workspace_resource_version',{'p_user':user_id,'p_resource':resource,'p_subject':subject_id}).execute().data
    except Exception as exc:
        code=getattr(exc,'code',None)
        if code=='42501':raise HTTPException(404,'科目不存在') from exc
        if code in {'22023','22P02'}:raise ValueError('Invalid workspace resource or subject scope') from exc
        raise RuntimeError('Workspace version validation is unavailable') from exc


def save_snapshot(*, user_id: str, resource: str, data: Any, subject_id: str | None = None, expected_version: str | None = None) -> dict:
    if resource not in RESOURCE_TTLS:
        raise ValueError("Unsupported workspace cache resource")
    if not expected_version:raise ValueError('expectedVersion is required')
    current=current_version(user_id=user_id,resource=resource,subject_id=subject_id)
    if expected_version!=current['version']:raise HTTPException(409,'学习记录已变化，旧快照不能保存')
    envelope = {
        "schemaVersion": 2,
        "version": expected_version,
        "resource": resource,
        "subjectId": subject_id,
        "cachedAt": datetime.now(UTC).isoformat(),
        "data": data,
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"),allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Workspace snapshot is too large")
    try:
        get_redis_client().setex(
            _key(user_id=user_id, resource=resource, subject_id=subject_id,version=expected_version),
            RESOURCE_TTLS[resource],
            encoded,
        )
    except RedisError as exc:
        logger.warning("Workspace cache write failed", extra={"resource": resource, "user_id": user_id})
        raise RuntimeError("Workspace cache is unavailable") from exc
    return {"cachedAt": envelope["cachedAt"], "resource": resource,'version':expected_version}


def load_snapshot(*, user_id: str, resource: str, subject_id: str | None = None) -> dict | None:
    if resource not in RESOURCE_TTLS:
        raise ValueError("Unsupported workspace cache resource")
    current=current_version(user_id=user_id,resource=resource,subject_id=subject_id)
    try:
        value = get_redis_client().get(_key(user_id=user_id, resource=resource, subject_id=subject_id,version=current['version']))
    except RedisError as exc:
        logger.warning("Workspace cache read failed", extra={"resource": resource, "user_id": user_id})
        raise RuntimeError("Workspace cache is unavailable") from exc
    if not value:
        return None
    try:
        envelope = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope,dict) or 'data' not in envelope or not isinstance(envelope.get('cachedAt'),str) or envelope.get('schemaVersion')!=2 or envelope.get('version')!=current['version'] or envelope.get('resource')!=resource or envelope.get('subjectId')!=subject_id:
        return None
    if current_version(user_id=user_id,resource=resource,subject_id=subject_id)['version']!=current['version']:return None
    return {**envelope, "stale": True,'versionVerified':True}


def cache_health() -> bool:
    try:
        return bool(get_redis_client().ping())
    except RedisError:
        return False


def reset_user_snapshots(*,user_id: str) -> None:
    """Revoke old generations before best-effort Redis erasure; failed erasure cannot revive old data."""
    normalized=str(UUID(user_id))
    get_supabase_client().rpc('revoke_workspace_snapshots',{'p_user':normalized}).execute()
    try:
        client=get_redis_client()
        for namespace in ('v1','v2'):
            batch=[]
            for key in client.scan_iter(match=f'workspace:{namespace}:{normalized}:*',count=100):
                batch.append(key)
                if len(batch)>=100:client.delete(*batch);batch=[]
            if batch:client.delete(*batch)
    except RedisError:
        logger.warning('Workspace snapshot erasure deferred to TTL; generations revoked',extra={'user_id':normalized})
