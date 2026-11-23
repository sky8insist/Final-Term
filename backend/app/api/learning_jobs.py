from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import learning_job_service as service

router=APIRouter()


@router.get('')
def list_jobs(subject_id: UUID,user: CurrentUser=Depends(get_current_user)):
    return service.list_jobs(user_id=user.id,subject_id=str(subject_id))


@router.post('/{job_id}/retry')
def retry(job_id: UUID,user: CurrentUser=Depends(get_current_user)):
    return service.retry(user_id=user.id,job_id=str(job_id))
