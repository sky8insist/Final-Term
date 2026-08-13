from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import workspace_cache_service

router = APIRouter()


class WorkspaceSnapshotRequest(BaseModel):
    data: Any
    subject_id: str | None = Field(default=None, validation_alias="subjectId")


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
            subject_id=payload.subject_id,
            data=payload.data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/cache/{resource}")
def get_workspace_snapshot(
    resource: str,
    subject_id: str | None = Query(default=None, alias="subjectId"),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        snapshot = workspace_cache_service.load_snapshot(
            user_id=current_user.id,
            resource=resource,
            subject_id=subject_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cached workspace snapshot")
    return snapshot


@router.get("/cache-health")
def workspace_cache_health(current_user: CurrentUser = Depends(get_current_user)):
    return {"available": workspace_cache_service.cache_health()}
