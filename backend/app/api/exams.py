from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import get_current_user
from app.models.exam import ExamGenerateRequest
from uuid import UUID
from app.models.user import CurrentUser
from app.services import exam_service
from app.services import exam_generation_service

router = APIRouter()


@router.post("/generations", status_code=202)
def queue_exam_generation(payload: ExamGenerateRequest,
                          current_user: CurrentUser = Depends(get_current_user)):
    task = exam_generation_service.create_generation_task(
        user_id=current_user.id, payload=payload,
    )
    if task["status"] == "queued":
        from app.worker.tasks import generate_exam
        generate_exam.delay(task["id"])
    return task


@router.get("")
def list_exams(subject_id: UUID, current_user: CurrentUser = Depends(get_current_user)):
    return exam_service.list_exams(user_id=current_user.id, subject_id=str(subject_id))


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
