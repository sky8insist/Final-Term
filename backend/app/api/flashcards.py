from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import flashcard_service

router = APIRouter()


@router.get("/queue")
def queue(subject_id: UUID | None = None, artifact_id: UUID | None = None,
          include_future: bool = False, limit: int = Query(50, ge=1, le=200),
          current_user: CurrentUser = Depends(get_current_user)):
    return flashcard_service.queue(user_id=current_user.id,
        subject_id=str(subject_id) if subject_id else None,
        artifact_id=str(artifact_id) if artifact_id else None,
        include_future=include_future, limit=limit)


@router.get("/{artifact_id}/cards/{card_id}/history")
def history(artifact_id: UUID, card_id: str,
            current_user: CurrentUser = Depends(get_current_user)):
    return flashcard_service.history(user_id=current_user.id, artifact_id=str(artifact_id), card_id=card_id)
