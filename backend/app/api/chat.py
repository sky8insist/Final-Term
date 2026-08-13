from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.chat import ChatRequest
from app.models.user import CurrentUser
from app.services import memory_service, rag_service

router = APIRouter()


@router.post("/ask")
async def ask_question(
    payload: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await rag_service.answer_with_rag(
        user_id=current_user.id,
        subject_id=payload.subject_id,
        question=payload.question,
        session_id=payload.session_id,
    )


@router.get("/history/{subject_id}")
async def list_chat_history(
    subject_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return memory_service.list_chat_history(user_id=current_user.id, subject_id=subject_id)
