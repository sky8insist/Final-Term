from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from uuid import UUID

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import workspace_cache_service

def no_store(response: Response):
    response.headers['Cache-Control']='no-store'


router = APIRouter(dependencies=[Depends(no_store)])


class WorkspaceSnapshotRequest(BaseModel):
    model_config={'extra':'forbid'}
    data: Any
    subject_id: UUID | None = Field(default=None, validation_alias="subjectId")
    expected_version: str = Field(validation_alias='expectedVersion',pattern='^[a-f0-9]{32}$')


@router.put("/cache/{resource}")
def save_workspace_snapshot(
    resource: str,
    payload: WorkspaceSnapshotRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return workspace_cache_service.save_snapshot(
            user_id=current_user.id,
            resource=resource,
            subject_id=str(payload.subject_id) if payload.subject_id else None,
            expected_version=payload.expected_version,
            data=payload.data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/cache/{resource}")
def get_workspace_snapshot(
    resource: str,
    subject_id: UUID | None = Query(default=None, alias="subjectId"),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        snapshot = workspace_cache_service.load_snapshot(
            user_id=current_user.id,
            resource=resource,
            subject_id=str(subject_id) if subject_id else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cached workspace snapshot")
    return snapshot


@router.get('/cache/{resource}/version')
def workspace_version(resource: str,subject_id: UUID | None = Query(default=None,alias='subjectId'),current_user: CurrentUser = Depends(get_current_user)):
    try:return workspace_cache_service.current_version(user_id=current_user.id,resource=resource,subject_id=str(subject_id) if subject_id else None)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(503,str(exc)) from exc


@router.get("/cache-health")
def workspace_cache_health(current_user: CurrentUser = Depends(get_current_user)):
    return {"available": workspace_cache_service.cache_health()}
