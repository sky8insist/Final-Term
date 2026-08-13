from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.exam import ExamGenerateRequest, QuestionTypeSpec
from app.models.user import CurrentUser
from app.services import exam_service

router = APIRouter()


class QuizRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    question_count: int = Field(default=10, ge=1, le=100, validation_alias="questionCount")
    difficulty: str = "medium"


@router.post("/generate")
async def generate_quiz(payload: QuizRequest,
                        current_user: CurrentUser = Depends(get_current_user)):
    exam_payload = ExamGenerateRequest(
        subjectId=payload.subject_id, title="专项练习", durationMinutes=max(payload.question_count * 3, 10),
        difficulty=payload.difficulty,
        questionTypes=[QuestionTypeSpec(questionType="single_choice", count=payload.question_count, pointsEach=1)],
    )
    return await exam_service.generate_exam(user_id=current_user.id, payload=exam_payload)
