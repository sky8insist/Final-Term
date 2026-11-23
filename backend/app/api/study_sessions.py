from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.study_session import SessionAction, SessionCreate, SessionMessage
from app.models.user import CurrentUser
from app.services import study_session_service as service

router = APIRouter()


@router.get("")
def sessions(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return service.list_sessions(user_id=user.id, subject_id=str(subject_id))


@router.post("")
def create(payload: SessionCreate, user: CurrentUser = Depends(get_current_user)):
    return service.create_session(user_id=user.id, payload=payload)


@router.get("/{session_id}")
def session(session_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return service.get_session(user_id=user.id, session_id=str(session_id))


@router.post("/{session_id}/actions")
async def action(session_id: UUID, payload: SessionAction, user: CurrentUser = Depends(get_current_user)):
    return await service.act(user_id=user.id, session_id=str(session_id), payload=payload)


@router.post("/{session_id}/messages")
async def message(session_id: UUID, payload: SessionMessage, user: CurrentUser = Depends(get_current_user)):
    return await service.message(user_id=user.id, session_id=str(session_id), text=payload.message)


@router.post("/{session_id}/quiz-attempt")
def quiz_attempt(session_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return service.quiz_attempt(user_id=user.id, session_id=str(session_id))
