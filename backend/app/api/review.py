from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.review import ReviewProgressUpdate
from app.models.user import CurrentUser
from app.services import memory_service

router = APIRouter()


@router.get("/{subject_id}/progress")
async def get_review_progress(
    subject_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return memory_service.get_review_progress(user_id=current_user.id, subject_id=subject_id)


@router.patch("/{subject_id}/progress")
async def update_review_progress(
    subject_id: str,
    payload: ReviewProgressUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    return memory_service.update_review_progress(
        user_id=current_user.id,
        subject_id=subject_id,
        mastered_count=payload.mastered_count,
        total_count=payload.total_count,
    )
