from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.config.settings import settings

logger = logging.getLogger(__name__)

RESOURCE_TTLS = {
    "dashboard": 300,
    "subjects": 900,
    "chat": 86400,
    "mind-map": 86400,
    "exams": 900,
    "plan": 600,
    "workspace": 604800,
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


def _key(*, user_id: str, resource: str, subject_id: str | None) -> str:
    scope = subject_id or "global"
    return f"workspace:v1:{user_id}:{resource}:{scope}"


def save_snapshot(*, user_id: str, resource: str, data: Any, subject_id: str | None = None) -> dict:
    if resource not in RESOURCE_TTLS:
        raise ValueError("Unsupported workspace cache resource")
    envelope = {
        "schemaVersion": 1,
        "resource": resource,
        "subjectId": subject_id,
        "cachedAt": datetime.now(UTC).isoformat(),
        "data": data,
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Workspace snapshot is too large")
    try:
        get_redis_client().setex(
            _key(user_id=user_id, resource=resource, subject_id=subject_id),
            RESOURCE_TTLS[resource],
            encoded,
        )
    except RedisError as exc:
        logger.warning("Workspace cache write failed", extra={"resource": resource, "user_id": user_id})
        raise RuntimeError("Workspace cache is unavailable") from exc
    return {"cachedAt": envelope["cachedAt"], "resource": resource}


def load_snapshot(*, user_id: str, resource: str, subject_id: str | None = None) -> dict | None:
    if resource not in RESOURCE_TTLS:
        raise ValueError("Unsupported workspace cache resource")
    try:
        value = get_redis_client().get(_key(user_id=user_id, resource=resource, subject_id=subject_id))
    except RedisError as exc:
        logger.warning("Workspace cache read failed", extra={"resource": resource, "user_id": user_id})
        raise RuntimeError("Workspace cache is unavailable") from exc
    if not value:
        return None
    try:
        envelope = json.loads(value)
    except json.JSONDecodeError:
        return None
    if envelope.get("schemaVersion") != 1:
        return None
    return {**envelope, "stale": True}


def cache_health() -> bool:
    try:
        return bool(get_redis_client().ping())
    except RedisError:
        return False
