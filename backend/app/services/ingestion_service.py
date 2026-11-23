from app.services.owner_io_service import serialized_owner
from hashlib import sha256
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, UploadFile, status

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import material_service, task_service
from app.services.file_service import normalized_upload_content_type, validate_upload_file
from app.services.observability_service import current_trace_metadata
from app.services.subject_service import get_subject


def _object_path(user_id: str, subject_id: str, digest: str, filename: str,
                 material_id: str | None = None) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"{user_id}/{subject_id}/{material_id or digest}/{digest}/{safe_name}"


def processing_summary(*, user_id: str, subject_id: str) -> list[dict]:
    get_subject(user_id=user_id, subject_id=subject_id)
    rows = get_supabase_client().rpc("material_processing_summary", {
        "p_user": user_id, "p_subject": subject_id,
    }).execute().data
    return [{**row, "task": task_service._serialize(row["task"]) if row.get("task") else None}
            for row in (rows or [])]


def dispatch_material(*, user_id: str, task_id: str) -> dict | None:
    """Surface broker failure as a retryable task instead of a stranded queue row."""
    from app.worker.tasks import process_material
    try:
        process_material.delay(task_id)
    except Exception:
        row = get_supabase_client().rpc("fail_material_dispatch", {
            "p_user": user_id, "p_task": task_id,
        }).execute().data
        return task_service._serialize(row)
    return None


@serialized_owner
def queue_upload(*, user_id: str, subject_id: str, file: UploadFile,
                 material_purpose: str = "learning", notes_mode: str | None = None) -> dict:
    if material_purpose not in {"learning", "syllabus", "reference"}:
        raise HTTPException(422, "Unsupported material purpose")
    if notes_mode is not None and notes_mode not in {'summary', 'standard', 'comprehensive', 'exam_focus'}:
        raise HTTPException(422, 'Unsupported Notes mode')
    get_subject(user_id=user_id, subject_id=subject_id)
    file_size = validate_upload_file(file)
    filename = (file.filename or "").strip()
    file.file.seek(0)
    data = file.file.read()
    digest = sha256(data).hexdigest()
    content_type = normalized_upload_content_type(file)
    client = get_supabase_client()
    duplicate = (
        client.table("materials").select(material_service.MATERIAL_SELECT)
        .eq("user_id", user_id).eq("subject_id", subject_id)
        .eq("source_hash", digest).neq("status", "failed").limit(1).execute()
    )
    if duplicate.data:
        existing = material_service._to_material(duplicate.data[0])
        if existing["materialPurpose"] != material_purpose:
            raise HTTPException(409, "该文件已按其他用途上传，请使用资料列表中的现有文件")
        if notes_mode:
            from app.services.material_notes_service import configure, enqueue_for_material
            existing = material_service._to_material(configure(user_id=user_id, material_id=existing['id'], mode=notes_mode))
            try:
                enqueue_for_material(user_id=user_id, subject_id=subject_id, material_id=existing['id'])
            except Exception:
                pass  # Saved intent is retried by Beat; the existing file remains usable.
        task_rows = (
            client.table("processing_tasks").select(task_service.TASK_SELECT)
            .eq("user_id", user_id).eq("material_id", existing["id"])
            .eq("task_type", "material_ingestion")
            .order("created_at", desc=True).limit(1).execute()
        )
        return {"material": existing, "task": task_service._serialize(task_rows.data[0]) if task_rows.data else None, "deduplicated": True}
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

    material = material_service.create_queued_material(
        user_id=user_id, subject_id=subject_id, filename=filename,
        content_type=content_type, file_size=file_size, source_hash=digest,
        material_purpose=material_purpose,
        upload_notes_mode=notes_mode,
    )
    object_path = _object_path(user_id, subject_id, digest, filename, material["id"])
    try:
        client.rpc('prepare_material_upload', {
            'p_user': user_id, 'p_material': material['id'], 'p_bucket': settings.material_storage_bucket,
            'p_path': object_path, 'p_hash': digest,
        }).execute()
        client.storage.from_(settings.material_storage_bucket).upload(
            path=object_path, file=data,
            file_options={"content-type": content_type, "upsert": "false"},
        )
        row = client.rpc('register_material_upload', {
            'p_user': user_id, 'p_material': material['id'],
            'p_asset': {'bucket': settings.material_storage_bucket, 'object_path': object_path,
                        'sha256': digest, 'expires_at': (datetime.now(UTC) + timedelta(days=settings.original_file_retention_days)).isoformat()},
            'p_metadata': {**current_trace_metadata(), 'materialPurpose': material_purpose},
            'p_attempts': settings.task_max_retries,
        }).execute().data
        task = task_service._serialize(row)
    except Exception as exc:
        material_service._update_material_status(
            client=client, user_id=user_id, material_id=material["id"],
            status_value="failed", error_message="Unable to persist uploaded file",
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to persist uploaded file") from exc

    dispatch_result = dispatch_material(user_id=user_id, task_id=task["id"])
    if dispatch_result:
        task = dispatch_result
        if task["status"] == "failed":
            material = {**material, "status": "failed", "errorMessage": task["errorMessage"]}
    return {"material": material, "task": task, "deduplicated": False}
