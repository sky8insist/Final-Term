from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import task_service

router = APIRouter()


@router.get("")
def list_tasks(subject_id: str | None = None, active_only: bool = False,
               current_user: CurrentUser = Depends(get_current_user)):
    return task_service.list_tasks(
        user_id=current_user.id, subject_id=subject_id, active_only=active_only,
    )


@router.get("/{task_id}")
def get_task(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return task_service.get_task(user_id=current_user.id, task_id=task_id)


@router.post("/{task_id}/retry")
def retry_task(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    task = task_service.retry_task(user_id=current_user.id, task_id=task_id)
    from app.worker.tasks import process_material
    process_material.delay(task_id)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_200_OK)
def cancel_task(task_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return task_service.cancel_task(user_id=current_user.id, task_id=task_id)
