import hashlib
import json
from uuid import uuid4

from app.db.supabase_client import get_supabase_client
from app.services import task_service
from app.services.observability_service import current_trace_metadata


def payload_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def create_generation_task(
    *, user_id: str, payload, task_type: str, idempotency_prefix: str,
    result_metadata: dict,
) -> dict:
    request_data = payload.model_dump(by_alias=True)
    fingerprint = payload_fingerprint(request_data)
    active = (
        get_supabase_client().table("processing_tasks")
        .select(task_service.TASK_SELECT)
        .eq("user_id", user_id)
        .eq("subject_id", payload.subject_id)
        .eq("task_type", task_type)
        .in_("status", ["queued", "running"])
        .contains("metadata", {"fingerprint": fingerprint})
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if active:
        return task_service._serialize(active[0])
    return task_service.create_task(
        user_id=user_id,
        subject_id=payload.subject_id,
        material_id=None,
        idempotency_key=f"{idempotency_prefix}:{fingerprint}:{uuid4()}",
        task_type=task_type,
        max_attempts=1,
        metadata={
            "fingerprint": fingerprint,
            "request": request_data,
            "currentStage": "queued",
            **current_trace_metadata(),
            **result_metadata,
        },
    )
