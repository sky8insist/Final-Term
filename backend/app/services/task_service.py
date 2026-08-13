from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.models.task import ProcessingTask

TASK_SELECT = "id,subject_id,material_id,task_type,status,stage,progress,attempts,max_attempts,error_code,error_message,metadata,created_at,updated_at"


def _serialize(row: dict) -> dict:
    return ProcessingTask(**row).model_dump(by_alias=True)


def create_task(*, user_id: str, subject_id: str, material_id: str, idempotency_key: str) -> dict:
    client = get_supabase_client()
    existing = (
        client.table("processing_tasks")
        .select(TASK_SELECT)
        .eq("user_id", user_id)
        .eq("idempotency_key", idempotency_key)
        .limit(1)
        .execute()
    )
    if existing.data:
        return _serialize(existing.data[0])
    response = (
        client.table("processing_tasks")
        .insert({
            "user_id": user_id,
            "subject_id": subject_id,
            "material_id": material_id,
            "idempotency_key": idempotency_key,
            "max_attempts": settings.task_max_retries,
        })
        .select(TASK_SELECT)
        .execute()
    )
    return _serialize(response.data[0])


def get_task(*, user_id: str, task_id: str) -> dict:
    response = (
        get_supabase_client().table("processing_tasks").select(TASK_SELECT)
        .eq("id", task_id).eq("user_id", user_id).limit(1).execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Task not found")
    return _serialize(response.data[0])


def list_tasks(*, user_id: str, subject_id: str | None = None,
               active_only: bool = False, limit: int = 100) -> list[dict]:
    query = (
        get_supabase_client().table("processing_tasks").select(TASK_SELECT)
        .eq("user_id", user_id)
    )
    if subject_id:
        query = query.eq("subject_id", subject_id)
    if active_only:
        query = query.in_("status", ["queued", "running"])
    rows = query.order("created_at", desc=True).limit(min(max(limit, 1), 200)).execute().data
    return [_serialize(row) for row in rows]


def update_task(*, user_id: str, task_id: str, **changes) -> dict:
    response = (
        get_supabase_client().table("processing_tasks").update(changes)
        .eq("id", task_id).eq("user_id", user_id).select(TASK_SELECT).execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Task not found")
    return _serialize(response.data[0])


def cancel_task(*, user_id: str, task_id: str) -> dict:
    task = get_task(user_id=user_id, task_id=task_id)
    if task["status"] in {"succeeded", "failed", "cancelled"}:
        return task
    return update_task(
        user_id=user_id, task_id=task_id, status="cancelled", stage="cancelled",
        error_message=None, finished_at=datetime.now(UTC).isoformat(),
    )


def retry_task(*, user_id: str, task_id: str) -> dict:
    task = get_task(user_id=user_id, task_id=task_id)
    if task["status"] != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed tasks can be retried")
    if task["attempts"] >= task["maxAttempts"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task retry limit reached")
    retried = update_task(
        user_id=user_id, task_id=task_id, status="queued", stage="queued",
        progress=0, error_code=None, error_message=None, finished_at=None,
    )
    if task.get("materialId"):
        get_supabase_client().table("materials").update({
            "status": "queued", "error_message": None,
        }).eq("id", task["materialId"]).eq("user_id", user_id).execute()
    return retried
