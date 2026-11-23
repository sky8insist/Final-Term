from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import daily_review_service as service
from app.services import learning_job_service

router = APIRouter()


class ReviewRequest(BaseModel):
    model_config = {'extra':'forbid'}
    subject_id: UUID = Field(alias='subjectId')
    request_id: UUID = Field(alias='requestId')


class ReviewDecision(BaseModel):
    model_config = {'extra':'forbid'}
    version: int = Field(ge=1)
    approve: bool = Field(strict=True)


class ReviewSchedule(BaseModel):
    model_config = {'extra':'forbid'}
    enabled: bool = Field(strict=True)
    hour: int = Field(ge=0,le=23)
    version: int = Field(ge=0)


@router.get('/schedule')
def schedule(subject_id: UUID,user: CurrentUser = Depends(get_current_user)):
    return learning_job_service.schedule(user_id=user.id,subject_id=str(subject_id))


@router.put('/schedule')
def save_schedule(subject_id: UUID,payload: ReviewSchedule,user: CurrentUser = Depends(get_current_user)):
    return learning_job_service.save_schedule(user_id=user.id,subject_id=str(subject_id),**payload.model_dump())


@router.post('')
def create(payload: ReviewRequest, user: CurrentUser = Depends(get_current_user)):
    return service.create(user_id=user.id,subject_id=str(payload.subject_id),request_id=str(payload.request_id))


@router.get('/preview')
def preview(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return service.preview(user_id=user.id,subject_id=str(subject_id))


@router.get('')
def history(subject_id: UUID, before: datetime | None = None, before_id: UUID | None = None, user: CurrentUser = Depends(get_current_user)):
    return service.history(user_id=user.id,subject_id=str(subject_id),before=before.isoformat() if before else None,before_id=str(before_id) if before_id else None)


@router.get('/{review_id}')
def get(review_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return service.get(user_id=user.id,review_id=str(review_id))


@router.post('/{review_id}/decision')
def decide(review_id: UUID,payload: ReviewDecision,user: CurrentUser = Depends(get_current_user)):
    return service.decide(user_id=user.id,review_id=str(review_id),version=payload.version,approve=payload.approve)
