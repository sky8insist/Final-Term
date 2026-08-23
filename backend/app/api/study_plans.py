from fastapi import APIRouter, Depends
from uuid import UUID

from app.api.deps import get_current_user
from app.models.study_plan import ReviewTaskUpdate, StudyPlanRequest
from app.models.user import CurrentUser
from app.services import study_plan_generation_service, study_plan_service, task_service

router = APIRouter()


@router.post("")
def generate_plan(payload: StudyPlanRequest,
                  current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.generate_plan(
        user_id=current_user.id, subject_id=payload.subject_id,
        exam_date=payload.exam_date, daily_minutes=payload.daily_minutes,
        title=payload.title, weekend_extra=payload.weekend_extra,
        reserve_final_day=payload.reserve_final_day, preserve_existing=payload.preserve_existing,
    )


@router.post("/preview")
def preview_plan(payload: StudyPlanRequest,
                 current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.preview_plan(
        user_id=current_user.id, subject_id=payload.subject_id,
        exam_date=payload.exam_date, daily_minutes=payload.daily_minutes,
        reserve_final_day=payload.reserve_final_day, weekend_extra=payload.weekend_extra,
    )


@router.post("/generations", status_code=202)
def queue_generation(payload: StudyPlanRequest,
                     current_user: CurrentUser = Depends(get_current_user)):
    task = study_plan_generation_service.create_generation_task(user_id=current_user.id, payload=payload)
    if task["status"] == "queued":
        from app.worker.tasks import generate_study_plan
        generate_study_plan.delay(task["id"])
    return task


@router.get("/generations/{generation_id}")
def generation_status(generation_id: str,
                      current_user: CurrentUser = Depends(get_current_user)):
    return task_service.get_task(user_id=current_user.id, task_id=generation_id)


@router.get("/today")
def today_tasks(subject_id: UUID | None = None,
                current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.today_tasks(
        user_id=current_user.id,
        subject_id=str(subject_id) if subject_id else None,
    )


@router.get("/overview")
def overview(subject_id: UUID | None = None,
             current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.plan_overview(
        user_id=current_user.id,
        subject_id=str(subject_id) if subject_id else None,
    )


@router.post("/{plan_id}/sprint")
def activate_sprint(plan_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.activate_sprint(
        user_id=current_user.id, plan_id=plan_id,
    )


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: ReviewTaskUpdate,
                current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.update_task(
        user_id=current_user.id, task_id=task_id, task_status=payload.status,
        scheduled_date=payload.scheduled_date, estimated_minutes=payload.estimated_minutes,
    )
