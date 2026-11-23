from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.exam import ConfirmResponseRequest, SaveResponseRequest, StartAttemptRequest
from app.models.exam import ResumeQuizRequest
from app.models.user import CurrentUser
from app.services import exam_service

router = APIRouter()


@router.post("/{attempt_id}/resume-quiz")
def resume_quiz(attempt_id: str, payload: ResumeQuizRequest, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.resume_quiz(user_id=current_user.id, attempt_id=attempt_id, note=payload.remediation_note)


@router.get("/history")
def assessment_history(subject_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.list_assessment_history(user_id=current_user.id, subject_id=subject_id)


@router.get("/{attempt_id}")
def get_attempt(attempt_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.get_attempt(user_id=current_user.id, attempt_id=attempt_id)


@router.post("")
def start_attempt(payload: StartAttemptRequest,
                  current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.start_attempt(user_id=current_user.id, exam_id=payload.exam_id)


@router.patch("/{attempt_id}/responses")
def save_response(attempt_id: str, payload: SaveResponseRequest,
                  current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.save_response(
        user_id=current_user.id, attempt_id=attempt_id,
        question_id=payload.question_id, response_value=payload.response,
        learner_confidence=payload.learner_confidence,
        response_seconds=payload.response_seconds, hint_count=payload.hint_count,
    )


@router.post("/{attempt_id}/questions/{question_id}/confirm")
async def confirm_response(attempt_id: str, question_id: str, payload: ConfirmResponseRequest,
                           current_user: CurrentUser = Depends(get_current_user)):
    return await exam_service.confirm_response(
        user_id=current_user.id, attempt_id=attempt_id,
        question_id=question_id, response_value=payload.response,
        learner_confidence=payload.learner_confidence,
        response_seconds=payload.response_seconds, hint_count=payload.hint_count,
    )


@router.post("/{attempt_id}/submit")
async def submit_attempt(attempt_id: str,
                         current_user: CurrentUser = Depends(get_current_user)):
    return await exam_service.submit_attempt(user_id=current_user.id, attempt_id=attempt_id)
