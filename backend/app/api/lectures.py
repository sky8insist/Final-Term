from typing import Literal
from uuid import UUID

from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel,ConfigDict,Field

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import lecture_service as service

router=APIRouter()


@router.get('/capabilities')
def capabilities(user:CurrentUser=Depends(get_current_user)):
    import shutil
    from app.config.settings import settings
    return {'maxRecordingSeconds':settings.max_audio_minutes*60,'maxUploadBytes':settings.max_upload_mb*1024*1024,
            'canProcessAudio':bool(shutil.which('ffmpeg') and shutil.which('ffprobe')),'mocked':settings.mock_external_apis}


class Attach(BaseModel):
    model_config=ConfigDict(extra='forbid')
    subject_id:UUID
    material_id:UUID
    title:str=Field(min_length=1,max_length=300)
    source_kind:Literal['recording','upload']='upload'


class Align(BaseModel):
    model_config=ConfigDict(extra='forbid')
    topic_id:UUID|None
    version:int=Field(ge=1)


@router.get('')
def list_lectures(subject_id:UUID,user:CurrentUser=Depends(get_current_user)):
    return service.list_lectures(user_id=user.id,subject_id=str(subject_id))


@router.get('/audio-materials')
def audio_materials(subject_id:UUID,user:CurrentUser=Depends(get_current_user)):
    return service.audio_materials(user_id=user.id,subject_id=str(subject_id))


@router.post('')
def attach(payload:Attach,user:CurrentUser=Depends(get_current_user)):
    values=payload.model_dump(mode='json')
    return service.attach(user_id=user.id,**values)


@router.get('/{lecture_id}')
def detail(lecture_id:UUID,subject_id:UUID,user:CurrentUser=Depends(get_current_user)):
    return service.get_lecture(user_id=user.id,lecture_id=str(lecture_id),subject_id=str(subject_id))


@router.get('/{lecture_id}/transcript')
def transcript(lecture_id:UUID,offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=100),block_id:UUID|None=None,user:CurrentUser=Depends(get_current_user)):
    return service.transcript(user_id=user.id,lecture_id=str(lecture_id),offset=offset,limit=limit,block_id=str(block_id) if block_id else None)


@router.put('/{lecture_id}/blocks/{block_id}/topic')
def align(lecture_id:UUID,block_id:UUID,payload:Align,user:CurrentUser=Depends(get_current_user)):
    return service.align(user_id=user.id,lecture_id=str(lecture_id),block_id=str(block_id),topic_id=str(payload.topic_id) if payload.topic_id else None,version=payload.version)
