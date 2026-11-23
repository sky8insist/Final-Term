from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.conversion import CAPABILITIES, ConversionRequest
from app.models.user import CurrentUser
from app.services import conversion_service

router = APIRouter()


@router.get('/capabilities')
def capabilities(user: CurrentUser = Depends(get_current_user)):
    return CAPABILITIES


@router.post('', status_code=202)
def create(payload: ConversionRequest, user: CurrentUser = Depends(get_current_user)):
    job = conversion_service.enqueue(user_id=user.id, payload=payload)
    conversion_service.dispatch(job['id'])
    return job


@router.get('')
def history(subject_id: UUID, object_id: UUID | None = None, user: CurrentUser = Depends(get_current_user)):
    return conversion_service.list_conversions(user_id=user.id, subject_id=str(subject_id),
        object_id=str(object_id) if object_id else None)


@router.get('/wrong-answers')
def wrong_answers(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return conversion_service.list_wrong_answers(user_id=user.id, subject_id=str(subject_id))


@router.get('/{conversion_id}')
def get(conversion_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return conversion_service.get_conversion(user_id=user.id, conversion_id=str(conversion_id))


@router.get('/{conversion_id}/tutor-context')
def tutor_context(conversion_id: UUID, subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return conversion_service.tutor_context(user_id=user.id, subject_id=str(subject_id), conversion_id=str(conversion_id))
