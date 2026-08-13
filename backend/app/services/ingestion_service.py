from hashlib import sha256
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, UploadFile, status

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import material_service, task_service
from app.services.file_service import normalized_upload_content_type, validate_upload_file
from app.services.subject_service import get_subject


def _object_path(user_id: str, subject_id: str, digest: str, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"{user_id}/{subject_id}/{digest}/{safe_name}"


def queue_upload(*, user_id: str, subject_id: str, file: UploadFile) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    file_size = validate_upload_file(file)
    filename = (file.filename or "").strip()
    file.file.seek(0)
    data = file.file.read()
    digest = sha256(data).hexdigest()
    content_type = normalized_upload_content_type(file)
    client = get_supabase_client()
    active = (
        client.table("processing_tasks").select("id").eq("user_id", user_id)
        .in_("status", ["queued", "running"]).execute().data
    )
    if len(active) >= settings.max_active_tasks_per_user:
        raise HTTPException(status_code=429, detail="Too many active processing tasks")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_assets = (
        client.table("material_assets").select("file_size").eq("user_id", user_id)
        .gte("created_at", today.isoformat()).execute().data
    )
    used_bytes = sum(int(item.get("file_size", 0)) for item in daily_assets)
    if used_bytes + file_size > settings.max_daily_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=429, detail="Daily upload quota exceeded")

    duplicate = (
        client.table("materials")
        .select(material_service.MATERIAL_SELECT)
        .eq("user_id", user_id).eq("subject_id", subject_id)
        .eq("source_hash", digest).neq("status", "failed").limit(1).execute()
    )
    if duplicate.data:
        existing = material_service._to_material(duplicate.data[0])
        task_rows = (
            client.table("processing_tasks").select(task_service.TASK_SELECT)
            .eq("user_id", user_id).eq("material_id", existing["id"])
            .order("created_at", desc=True).limit(1).execute()
        )
        return {"material": existing, "task": task_service._serialize(task_rows.data[0]) if task_rows.data else None, "deduplicated": True}

    material = material_service.create_queued_material(
        user_id=user_id, subject_id=subject_id, filename=filename,
        content_type=content_type, file_size=file_size, source_hash=digest,
    )
    object_path = _object_path(user_id, subject_id, digest, filename)
    try:
        client.storage.from_(settings.material_storage_bucket).upload(
            path=object_path, file=data,
            file_options={"content-type": content_type, "upsert": "false"},
        )
        client.table("material_assets").insert({
            "user_id": user_id, "subject_id": subject_id,
            "material_id": material["id"], "asset_type": "original",
            "bucket": settings.material_storage_bucket, "object_path": object_path,
            "content_type": content_type, "file_size": file_size, "sha256": digest,
            "expires_at": (
                datetime.now(UTC) + timedelta(days=settings.original_file_retention_days)
            ).isoformat(),
        }).execute()
        task = task_service.create_task(
            user_id=user_id, subject_id=subject_id, material_id=material["id"],
            idempotency_key=f"material:{material['id']}:{digest}",
        )
    except Exception as exc:
        material_service._update_material_status(
            client=client, user_id=user_id, material_id=material["id"],
            status_value="failed", error_message="Unable to persist uploaded file",
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to persist uploaded file") from exc

    from app.worker.tasks import process_material
    process_material.delay(task["id"])
    return {"material": material, "task": task, "deduplicated": False}
