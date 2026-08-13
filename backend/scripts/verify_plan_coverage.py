"""Static acceptance matrix for the numbered implementation plan.

This does not replace service integration tests. It prevents a phase from being
reported as implemented when its migrations, API contract, worker, or frontend
entry point has disappeared during refactoring.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


def contains(relative: str, *needles: str) -> bool:
    text = (ROOT / relative).read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


paths = set(app.openapi()["paths"])
checks: dict[int, list[tuple[str, bool]]] = {
    0: [("API v1", "/api/v1/subjects" in paths), ("UTF-8 editor config", (ROOT / ".editorconfig").exists())],
    1: [("async task migration", contains("backend/migrations/007_processing_tasks_assets.sql", "processing_tasks", "material_assets", "storage.buckets")),
        ("upload/task APIs", all(path in paths for path in ("/api/v1/materials/uploads", "/api/v1/tasks/{task_id}", "/api/v1/tasks/{task_id}/retry")))],
    2: [
        ("content blocks", contains("backend/migrations/008_content_blocks.sql", "content_blocks", "structured_data", "bounding_box")),
        ("traceable vector chunks", contains(
            "backend/migrations/019_traceable_material_chunks.sql",
            "content_block_id", "page_number", "bounding_box", "start_time", "end_time",
        )),
    ],
    3: [("document parsers", contains("backend/app/services/parse_service.py", "gb18030", "pymupdf", "python-docx"))],
    4: [("vision schema", contains("backend/app/services/multimodal_service.py", '"table"', '"chart"', '"formula"'))],
    5: [
        ("audio timestamps", contains("backend/app/services/parse_service.py", 'block["start_time"]', "analyze_transcript")),
        ("audio segmentation", contains(
            "backend/app/services/audio_service.py",
            "silencedetect", "audio_segment_seconds", "_extract_wav_segment",
        )),
        ("segment retry state", contains(
            "backend/migrations/020_audio_segment_processing.sql",
            "audio_segments", "transcribing", "transcription",
        )),
    ],
    6: [("hybrid retrieval", contains("backend/app/services/retrieval_service.py", '"lightrag"', '"keyword"', '"vector"')),
        ("Chinese structured search", contains("backend/migrations/015_chinese_structured_retrieval.sql", "pg_trgm", "structured_data::text"))],
    7: [("Hermes storage", contains("backend/migrations/010_hermes_memory.sql", "memory_snapshots", "memory_write_requests", "procedural_skills")),
        ("memory APIs", all(path in paths for path in ("/api/v1/memories", "/api/v1/memory-writes/pending", "/api/v1/sessions/search")))],
    8: [("unified assistant", "/api/v1/assistant/messages" in paths), ("intent schema", contains("backend/app/models/assistant.py", "generate_exam", "external_research"))],
    9: [("seven roles", contains("backend/app/services/role_service.py", "beginner", "crash_course", "socratic", "examiner", "mistake_coach", "academic", "sprint_planner"))],
    10: [("external source boundary", contains("backend/app/services/rag_service.py", "课程资料依据", "外部补充知识")),
         ("subject opt-in", contains("backend/migrations/016_subject_external_knowledge.sql", "external_knowledge_enabled"))],
    11: [("artifacts", contains("backend/migrations/011_artifacts.sql", "artifacts")), ("artifact API", "/api/v1/artifacts" in paths),
         ("map UI", contains("frontend/src/App.tsx", "/subjects/:subjectId/map"))],
    12: [("exam schema", contains("backend/migrations/012_exams.sql", "exam_blueprints", "grading_results", "wrong_answers")),
         ("attempt API", "/api/v1/exam-attempts/{attempt_id}/submit" in paths)],
    13: [("plans", contains("backend/migrations/013_study_plans.sql", "study_plans", "review_tasks")),
         ("today API", "/api/v1/study-plans/today" in paths)],
    14: [("formal routes", contains("frontend/src/App.tsx", "/dashboard", "/profile", "/plans", "/wrong-answers")),
         ("persistent task queue", contains("frontend/src/pages/UploadMaterial.tsx", "listProcessingTasks"))],
    15: [("operations migration", contains("backend/migrations/024_operation_metrics.sql", "operation_metrics", "duration_ms")),
         ("operations API", "/api/v1/operations/metrics" in paths),
         ("privacy API", all(path in paths for path in ("/api/v1/privacy/export", "/api/v1/privacy/data", "/api/v1/privacy/account"))),
         ("budget", contains("backend/app/services/observability_service.py", "ensure_model_budget", "estimated_cost")),
         ("provider adapter", contains("backend/app/providers/openai_compatible.py", "OpenAICompatibleProvider", "get_model_provider")),
         ("backup verification", contains("backend/scripts/backup_restore.py", "pg_dump", "pg_restore", "sha256")),
         ("CI", (ROOT / ".github" / "workflows" / "ci.yml").exists())],
}

failed = []
for step, items in checks.items():
    states = ", ".join(f"{name}={'OK' if passed else 'MISSING'}" for name, passed in items)
    print(f"STEP {step:02d}: {states}")
    failed.extend(f"step {step}: {name}" for name, passed in items if not passed)

if failed:
    raise SystemExit("PLAN COVERAGE FAILED: " + "; ".join(failed))
print("PLAN COVERAGE PASSED")
