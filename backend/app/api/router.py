from fastapi import APIRouter
from app.api import calendar
from app.api import daily_reviews
from app.api import learning_jobs
from app.api import lectures
from app.api import course, recommendations
from app.api import study_sessions, flashcards, notes, conversions

from app.api import artifacts, assistant, auth, chat, exam_attempts, exams, materials, memory, operations, privacy, retrieval, review, study_plans, subjects, tasks, workspace


def build_api_router() -> APIRouter:
    """Build the business router once per mounted API version."""
    router = APIRouter()
    router.include_router(daily_reviews.router,prefix='/daily-reviews',tags=['daily-reviews'])
    router.include_router(learning_jobs.router,prefix='/learning-jobs',tags=['learning-jobs'])
    router.include_router(calendar.router, prefix='/calendar', tags=['calendar'])
    router.include_router(lectures.router,prefix='/lectures',tags=['lectures'])
    router.include_router(auth.router, prefix="/auth", tags=["auth"])
    router.include_router(subjects.router, prefix="/subjects", tags=["subjects"])
    router.include_router(course.router, prefix="/courses", tags=["courses"])
    router.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
    router.include_router(study_sessions.router, prefix="/study-sessions", tags=["study-sessions"])
    router.include_router(flashcards.router, prefix="/flashcards", tags=["flashcards"])
    router.include_router(materials.router, prefix="/materials", tags=["materials"])
    router.include_router(retrieval.router, prefix="/retrieval", tags=["retrieval"])
    router.include_router(chat.router, prefix="/chat", tags=["chat"])
    router.include_router(review.router, prefix="/review", tags=["review"])
    router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
    router.include_router(memory.router, tags=["memory"])
    router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
    router.include_router(artifacts.router, prefix="/artifacts", tags=["artifacts"])
    router.include_router(notes.router, prefix="/notes", tags=["notes"])
    router.include_router(conversions.router, prefix="/conversions", tags=["conversions"])
    router.include_router(exams.router, prefix="/exams", tags=["exams"])
    router.include_router(study_plans.router, prefix="/study-plans", tags=["study-plans"])
    router.include_router(privacy.router, prefix="/privacy", tags=["privacy"])
    router.include_router(exam_attempts.router, prefix="/exam-attempts", tags=["exam-attempts"])
    router.include_router(operations.router, prefix="/operations", tags=["operations"])
    router.include_router(workspace.router, prefix="/workspace", tags=["workspace"])
    return router
