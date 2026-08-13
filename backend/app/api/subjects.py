from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import subject_service

router = APIRouter()


class SubjectCreateRequest(BaseModel):
    name: str
    description: str | None = None
    external_knowledge_enabled: bool = False


class SubjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    external_knowledge_enabled: bool | None = None


@router.get("")
async def list_subjects(current_user: CurrentUser = Depends(get_current_user)):
    return subject_service.list_subjects(user_id=current_user.id)


@router.post("")
async def create_subject(
    payload: SubjectCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return subject_service.create_subject(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        external_knowledge_enabled=payload.external_knowledge_enabled,
    )


@router.get("/{subject_id}")
async def get_subject(
    subject_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return subject_service.get_subject(user_id=current_user.id, subject_id=subject_id)


@router.patch("/{subject_id}")
async def update_subject(
    subject_id: str,
    payload: SubjectUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return subject_service.update_subject(
        user_id=current_user.id,
        subject_id=subject_id,
        name=payload.name,
        description=payload.description,
        external_knowledge_enabled=payload.external_knowledge_enabled,
    )


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    subject_service.delete_subject(user_id=current_user.id, subject_id=subject_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
