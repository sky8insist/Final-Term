from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import get_current_user
from app.models.exam import ExamGenerateRequest, SaveResponseRequest, StartAttemptRequest
from pydantic import BaseModel, Field
from app.models.user import CurrentUser
from app.services import exam_service

router = APIRouter()


class WrongAnswerUpdate(BaseModel):
    resolved: bool


class VariationRequest(BaseModel):
    count: int = Field(default=2, ge=1, le=10)


@router.post("")
async def generate_exam(payload: ExamGenerateRequest,
                        current_user: CurrentUser = Depends(get_current_user)):
    return await exam_service.generate_exam(user_id=current_user.id, payload=payload)


@router.get("")
def list_exams(subject_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.list_exams(user_id=current_user.id, subject_id=subject_id)


@router.get("/{exam_id}")
def get_exam(exam_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.get_exam(user_id=current_user.id, exam_id=exam_id, include_answers=False)


@router.get("/{exam_id}/export")
def export_exam(exam_id: str, format: str = Query("pdf"),
                include_answers: bool = Query(False, alias="includeAnswers"),
                current_user: CurrentUser = Depends(get_current_user)):
    data, media_type, filename = exam_service.export_exam(
        user_id=current_user.id, exam_id=exam_id,
        export_format=format.lower(), include_answers=include_answers,
    )
    return Response(content=data, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


@router.post("/attempts")
def start_attempt(payload: StartAttemptRequest,
                  current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.start_attempt(user_id=current_user.id, exam_id=payload.exam_id)


@router.patch("/attempts/{attempt_id}/responses")
def save_response(attempt_id: str, payload: SaveResponseRequest,
                  current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.save_response(
        user_id=current_user.id, attempt_id=attempt_id,
        question_id=payload.question_id, response_value=payload.response,
    )


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.get_attempt(user_id=current_user.id, attempt_id=attempt_id)


@router.post("/attempts/{attempt_id}/submit")
async def submit_attempt(attempt_id: str,
                         current_user: CurrentUser = Depends(get_current_user)):
    return await exam_service.submit_attempt(user_id=current_user.id, attempt_id=attempt_id)


@router.get("/wrong-answers/{subject_id}")
def wrong_answers(subject_id: str, resolved: bool | None = None,
                  current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.list_wrong_answers(
        user_id=current_user.id, subject_id=subject_id, resolved=resolved,
    )


@router.patch("/wrong-answers/{wrong_answer_id}")
def update_wrong_answer(wrong_answer_id: str, payload: WrongAnswerUpdate,
                        current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.resolve_wrong_answer(
        user_id=current_user.id, wrong_answer_id=wrong_answer_id, resolved=payload.resolved,
    )


@router.post("/wrong-answers/{wrong_answer_id}/variations")
async def wrong_answer_variations(wrong_answer_id: str, payload: VariationRequest,
                                  current_user: CurrentUser = Depends(get_current_user)):
    return await exam_service.generate_wrong_answer_variations(
        user_id=current_user.id, wrong_answer_id=wrong_answer_id, count=payload.count,
    )
