from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import artifact_service

router = APIRouter()


class OutlineRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    scope: str | None = None


@router.post("/generate")
async def generate_outline(payload: OutlineRequest,
                           current_user: CurrentUser = Depends(get_current_user)):
    return await artifact_service.generate_artifact(
        user_id=current_user.id, subject_id=payload.subject_id,
        artifact_type="outline", scope=payload.scope,
        material_ids=None, mode=None, count=30,
    )
