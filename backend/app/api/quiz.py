from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class QuizRequest(BaseModel):
    subject_id: str
    question_count: int = 10
    difficulty: str = "medium"


@router.post("/generate")
async def generate_quiz(payload: QuizRequest):
    return {"message": "quiz endpoint", "subject_id": payload.subject_id}
