from app.services.owner_io_service import serialized_owner

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.config.settings import settings
from app.services.lightrag_service import LightRAGServiceError, delete_material_index

USER_TABLES = [
    'material_upload_intents',
    "material_ingestion_checkpoints",
    'retention_receipts',
    'dayend_runs', 'dayend_night_states', 'lightrag_material_index',
    'mastery_prediction_coverage',
    'learning_metric_cohorts', 'mastery_prediction_samples',
    'recommendation_audits', 'product_events',
    'workspace_cache_versions',
    'learning_domain_events','learning_projection_versions',
    'daily_review_schedules','learning_job_outbox',
    'daily_learning_reviews',
    'mind_map_topic_links',
    "material_outlines", "material_topic_proposals",
    'lectures','lecture_topic_links',
    'calendar_availability', 'calendar_exam_proposals',
    'learning_conversions',
    "subjects", "materials", "content_blocks", "processing_tasks", "material_assets",
    "chat_messages", "review_progress", "memory_entries", "memory_write_requests",
    "memory_snapshots", "learning_events", "session_summaries", "knowledge_mastery",
    "procedural_skills", "artifacts", "exam_blueprints", "questions", "exams",
    "exam_attempts", "exam_responses", "grading_results", "wrong_answers",
    "study_plans", "review_tasks", "model_call_logs", "security_events",
    "operation_metrics",
    "audio_segments", "knowledge_points", "rubrics", "procedural_skill_versions",
    "mastery_history",
    "knowledge_units", "topic_aliases", "artifact_topics",
    "topic_coverage",
    "syllabi", "syllabus_topics", "exam_events", "exam_topic_map",
    "study_sessions", "study_session_steps",
    "study_plan_events",
    "learning_interactions",
    "flashcards", "flashcard_review_state", "flashcard_review_logs",
    "material_chunks", "parent_chunks", "parent_chunk_blocks",
    "artifact_versions", "note_sources",
]


def export_user_data(*, user_id: str) -> dict:
    try:
        payload = get_supabase_client().rpc('export_privacy_bundle', {'p_user': user_id}).execute().data
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
            raise ValueError('Invalid export response')
        return payload
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Data export unavailable; no partial export was returned') from exc


def _owned_rows(client, table: str, user_id: str, columns: str = '*') -> list[dict]:
    """Continue to an empty page even if the server applies a smaller row cap."""
    rows = []
    while True:
        page = (client.table(table).select(columns).eq('user_id', user_id)
                .order('id').range(len(rows), len(rows) + 99).execute().data)
        if not page:
            return rows
        rows.extend(page)


@serialized_owner
def delete_learning_data(*, user_id: str) -> dict:
    client = get_supabase_client()
    # Include failed/indexing records: they may have published partial indexes.
    index_rows = _owned_rows(client, 'lightrag_material_index', user_id)
    chunks = _owned_rows(client, 'material_chunks', user_id, 'id,material_id,subject_id,embedding_dimensions') if index_rows else []
    indexed: dict[str, dict] = {}
    for row in chunks:
        if row.get('embedding_dimensions') is not None:
            indexed.setdefault(str(row['material_id']), row)
    if any(str(row['material_id']) not in indexed for row in index_rows):
        raise HTTPException(status_code=502, detail='Index cleanup metadata is incomplete; relational data was retained')
    try:
        for index_row in index_rows:
            material_id = str(index_row['material_id'])
            row = indexed[material_id]
            delete_material_index(
                user_id=user_id, subject_id=str(row["subject_id"]), material_id=material_id,
                embedding_dimension=int(row["embedding_dimensions"]),
            )
    except LightRAGServiceError as exc:
        raise HTTPException(status_code=502, detail="LightRAG data deletion failed; no relational data was removed") from exc
    assets = _owned_rows(client, 'material_assets', user_id)
    assets += _owned_rows(client, 'material_upload_intents', user_id)
    if any(row['bucket'] != settings.material_storage_bucket
           or not row['object_path'].startswith(user_id + '/')
           or any(part in ('', '.', '..') for part in row['object_path'].split('/')) for row in assets):
        raise HTTPException(502, 'Stored file ownership could not be verified; relational data retained')
    storage_failures = []
    for group_bucket in {row["bucket"] for row in assets}:
        paths = sorted({row["object_path"] for row in assets if row["bucket"] == group_bucket})
        if paths:
            try:
                for start in range(0, len(paths), 100):
                    client.storage.from_(group_bucket).remove(paths[start:start + 100])
            except Exception:
                storage_failures.extend(paths)
    if storage_failures:
        raise HTTPException(status_code=502, detail={"message": "Some stored files could not be deleted", "count": len(storage_failures)})
    try:
        client.rpc('delete_privacy_learning_data', {'p_user': user_id}).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Relational cleanup failed and was rolled back; retry deletion') from exc
    from app.services.workspace_cache_service import reset_user_snapshots
    reset_user_snapshots(user_id=user_id)
    return {"deleted": True, "userId": user_id}


@serialized_owner
def delete_account(*, user_id: str, confirmation: str) -> dict:
    if confirmation != "DELETE":
        raise HTTPException(status_code=422, detail="Account deletion requires confirm=DELETE")
    delete_learning_data(user_id=user_id)
    try:
        get_supabase_client().auth.admin.delete_user(user_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Learning data was deleted, but auth account deletion failed") from exc
    return {"deleted": True}
