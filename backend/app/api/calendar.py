from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_user
from app.models.exam_goal import ExamEventSave
from app.models.user import CurrentUser
from app.services import calendar_service as service

router=APIRouter()


class Availability(BaseModel):
    model_config=ConfigDict(extra='forbid')
    minutes: int=Field(ge=0,le=1440)
    version: int=Field(ge=0)


class Move(BaseModel):
    model_config=ConfigDict(extra='forbid')
    day: date
    version: int=Field(ge=1)


class Source(BaseModel):
    model_config=ConfigDict(extra='forbid')
    subject_id: UUID
    material_id: UUID


@router.get('')
def calendar(start:date,end:date,subject_id:UUID|None=None,user:CurrentUser=Depends(get_current_user)):
    return service.calendar(user_id=user.id,start=start,end=end,subject_id=str(subject_id) if subject_id else None)


@router.put('/availability/{day}')
def availability(day:date,payload:Availability,user:CurrentUser=Depends(get_current_user)):
    return service.save_availability(user_id=user.id,day=day,**payload.model_dump())


@router.post('/tasks/{task_id}/move')
def move(task_id:UUID,payload:Move,user:CurrentUser=Depends(get_current_user)):
    return service.move_task(user_id=user.id,task_id=str(task_id),**payload.model_dump())


@router.post('/exam-proposals')
def propose(payload:Source,user:CurrentUser=Depends(get_current_user)):
    return service.propose(user_id=user.id,subject_id=str(payload.subject_id),material_id=str(payload.material_id))


@router.post('/exam-proposals/{proposal_id}/confirm')
def confirm(proposal_id:UUID,payload:ExamEventSave,user:CurrentUser=Depends(get_current_user)):
    return service.confirm(user_id=user.id,proposal_id=str(proposal_id),values=payload.model_dump(mode='json'))
