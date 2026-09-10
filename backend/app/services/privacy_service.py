from datetime import UTC, datetime

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.lightrag_service import LightRAGServiceError, delete_material_index

USER_TABLES = [
    "subjects", "materials", "content_blocks", "processing_tasks", "material_assets",
    "chat_messages", "review_progress", "memory_entries", "memory_write_requests",
    "memory_snapshots", "learning_events", "session_summaries", "knowledge_mastery",
    "procedural_skills", "artifacts", "exam_blueprints", "questions", "exams",
    "exam_attempts", "exam_responses", "grading_results", "wrong_answers",
    "study_plans", "review_tasks", "model_call_logs", "security_events",
    "operation_metrics",
    "audio_segments", "knowledge_points", "rubrics", "procedural_skill_versions",
    "mastery_history",
]


def export_user_data(*, user_id: str) -> dict:
    client = get_supabase_client()
    data = {}
    for table in USER_TABLES:
        try:
            data[table] = client.table(table).select("*").eq("user_id", user_id).execute().data
        except Exception:
            data[table] = []
    profile = client.table("learner_profiles").select("*").eq("user_id", user_id).execute().data
    data["learner_profiles"] = profile
    exam_ids = [row["id"] for row in data.get("exams", [])]
    question_ids = [row["id"] for row in data.get("questions", [])]
    data["exam_sections"] = client.table("exam_sections").select("*").in_("exam_id", exam_ids).execute().data if exam_ids else []
    data["exam_questions"] = client.table("exam_questions").select("*").in_("exam_id", exam_ids).execute().data if exam_ids else []
    data["question_versions"] = client.table("question_versions").select("*").in_("question_id", question_ids).execute().data if question_ids else []
    return {"exportedAt": datetime.now(UTC).isoformat(), "userId": user_id, "data": data}


def delete_learning_data(*, user_id: str) -> dict:
    client = get_supabase_client()
    exam_ids = [
        str(row["id"]) for row in
        client.table("exams").select("id").eq("user_id", user_id).execute().data
    ]
    question_ids = [
        str(row["id"]) for row in
        client.table("questions").select("id").eq("user_id", user_id).execute().data
    ]
    for table in ("wrong_answers", "grading_results", "exam_responses"):
        client.table(table).delete().eq("user_id", user_id).execute()
    client.table("exam_attempts").delete().eq("user_id", user_id).execute()
    if exam_ids:
        client.table("exam_questions").delete().in_("exam_id", exam_ids).execute()
        client.table("exam_sections").delete().in_("exam_id", exam_ids).execute()
        client.table("exams").delete().in_("id", exam_ids).eq("user_id", user_id).execute()
    if question_ids:
        client.table("exam_questions").delete().in_("question_id", question_ids).execute()
        client.table("question_versions").delete().in_("question_id", question_ids).execute()
        client.table("questions").delete().in_("id", question_ids).eq("user_id", user_id).execute()
    client.table("exam_blueprints").delete().eq("user_id", user_id).execute()
    index_rows = (
        client.table("lightrag_material_index")
        .select("material_id,subject_id,status")
        .eq("user_id", user_id).eq("status", "indexed").execute().data
    )
    material_ids = [str(row["material_id"]) for row in index_rows]
    chunks = (
        client.table("material_chunks")
        .select("material_id,subject_id,embedding_dimensions")
        .eq("user_id", user_id).in_("material_id", material_ids)
        .not_.is_("embedding_dimensions", "null").execute().data
        if material_ids else []
    )
    indexed: dict[str, dict] = {}
    for row in chunks:
        indexed.setdefault(str(row["material_id"]), row)
    try:
        for material_id, row in indexed.items():
            delete_material_index(
                user_id=user_id, subject_id=str(row["subject_id"]), material_id=material_id,
                embedding_dimension=int(row["embedding_dimensions"]),
            )
    except LightRAGServiceError as exc:
        raise HTTPException(status_code=502, detail="LightRAG data deletion failed; no relational data was removed") from exc
    assets = client.table("material_assets").select("bucket,object_path").eq("user_id", user_id).execute().data
    storage_failures = []
    for group_bucket in {row["bucket"] for row in assets}:
        paths = [row["object_path"] for row in assets if row["bucket"] == group_bucket]
        if paths:
            try:
                client.storage.from_(group_bucket).remove(paths)
            except Exception:
                storage_failures.extend(paths)
    if storage_failures:
        raise HTTPException(status_code=502, detail={"message": "Some stored files could not be deleted", "count": len(storage_failures)})
    # Subjects cascade through all subject-scoped learning records.
    client.table("subjects").delete().eq("user_id", user_id).execute()
    for table in ("memory_entries", "memory_write_requests", "memory_snapshots", "learning_events",
                  "session_summaries", "procedural_skills", "learner_profiles", "model_call_logs",
                  "operation_metrics"):
        client.table(table).delete().eq("user_id", user_id).execute()
    return {"deleted": True, "userId": user_id}


def delete_account(*, user_id: str, confirmation: str) -> dict:
    if confirmation != "DELETE":
        raise HTTPException(status_code=422, detail="Account deletion requires confirm=DELETE")
    delete_learning_data(user_id=user_id)
    try:
        get_supabase_client().auth.admin.delete_user(user_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Learning data was deleted, but auth account deletion failed") from exc
    return {"deleted": True}
