import hashlib
import json
from uuid import uuid4

from app.db.supabase_client import get_supabase_client
from app.services import task_service


def create_generation_task(*, user_id: str, payload) -> dict:
    request_data = payload.model_dump(by_alias=True)
    value = json.dumps(request_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    client = get_supabase_client()
    active = (client.table("processing_tasks").select(task_service.TASK_SELECT)
              .eq("user_id", user_id).eq("subject_id", payload.subject_id)
              .eq("task_type", "study_plan_generation").in_("status", ["queued", "running"])
              .contains("metadata", {"fingerprint": fingerprint}).order("created_at", desc=True).limit(1).execute().data)
    if active:
        return task_service._serialize(active[0])
    return task_service.create_task(
        user_id=user_id, subject_id=payload.subject_id, material_id=None,
        idempotency_key=f"study-plan:{fingerprint}:{uuid4()}", task_type="study_plan_generation", max_attempts=1,
        metadata={"fingerprint": fingerprint, "request": request_data, "currentStage": "queued", "planId": None},
    )
