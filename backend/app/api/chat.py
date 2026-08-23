from fastapi import APIRouter, Depends
from uuid import UUID

from app.api.deps import get_current_user
from app.models.chat import ChatRequest
from app.models.user import CurrentUser
from app.services import memory_service, rag_service

router = APIRouter()

TEACHING_INSTRUCTIONS = {
    "detail": "先给直接答案，再分步骤解释概念、关键词与相互关系。",
    "quick": "用精炼要点回答，突出最需要记忆的结论和易考点。",
    "socratic": "先准确回答，再提出一个基于资料的引导问题帮助学生继续思考。",
    "exam": "按考试作答标准组织答案，给出定义、得分点和常见失分点。",
}


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
        teaching_instruction=TEACHING_INSTRUCTIONS[payload.mode],
    )


@router.get("/history/{subject_id}")
async def list_chat_history(
    subject_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return memory_service.list_chat_history(user_id=current_user.id, subject_id=str(subject_id))
