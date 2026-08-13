from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.study_plan import ReviewTaskUpdate, StudyPlanRequest
from app.models.user import CurrentUser
from app.services import study_plan_service

router = APIRouter()


@router.post("")
def generate_plan(payload: StudyPlanRequest,
                  current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.generate_plan(
        user_id=current_user.id, subject_id=payload.subject_id,
        exam_date=payload.exam_date, daily_minutes=payload.daily_minutes,
        title=payload.title,
    )


@router.get("/today")
def today_tasks(subject_id: str | None = None,
                current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.today_tasks(user_id=current_user.id, subject_id=subject_id)


@router.get("/overview")
def overview(subject_id: str | None = None,
             current_user: CurrentUser = Depends(get_current_user)):
    return study_plan_service.plan_overview(
        user_id=current_user.id, subject_id=subject_id,
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
