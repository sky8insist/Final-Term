from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from uuid import UUID

from app.api.deps import get_current_user
from app.models.artifact import (
    ArtifactGenerateRequest,
    ArtifactScopedGenerateRequest,
    ArtifactUpdateRequest,
    MindMapGenerateRequest,
)
from app.models.user import CurrentUser
from app.services import artifact_service
from app.mindmap import service as mindmap_service

router = APIRouter()


class FlashcardReview(BaseModel):
    card_id: str = Field(validation_alias="cardId")
    rating: str
    response_seconds: float | None = Field(default=None, ge=0, validation_alias="responseSeconds")


async def _generate_as(payload: ArtifactScopedGenerateRequest, artifact_type: str, user_id: str):
    return await artifact_service.generate_artifact(
        user_id=user_id, subject_id=payload.subject_id, artifact_type=artifact_type,
        scope=payload.scope, material_ids=payload.material_ids, mode=payload.mode, count=payload.count,
    )


@router.post("/mind-maps")
async def generate_mind_map(payload: MindMapGenerateRequest,
                            current_user: CurrentUser = Depends(get_current_user)):
    return await mindmap_service.generate_mind_map(
        user_id=current_user.id,
        subject_id=payload.subject_id,
        mode=payload.mode,
        query=payload.query,
        topic_id=payload.topic_id,
        chapter_id=payload.chapter_id,
        max_depth=payload.max_depth,
        include_mastery=payload.include_mastery,
        material_ids=payload.material_ids,
        count=payload.count,
    )


@router.post("/outlines")
async def generate_outline(payload: ArtifactScopedGenerateRequest,
                           current_user: CurrentUser = Depends(get_current_user)):
    return await _generate_as(payload, "outline", current_user.id)


@router.post("/flashcards")
async def generate_flashcards(payload: ArtifactScopedGenerateRequest,
                              current_user: CurrentUser = Depends(get_current_user)):
    return await _generate_as(payload, "flashcards", current_user.id)


@router.post("")
async def generate_artifact(payload: ArtifactGenerateRequest,
                            current_user: CurrentUser = Depends(get_current_user)):
    return await artifact_service.generate_artifact(
        user_id=current_user.id, subject_id=payload.subject_id,
        artifact_type=payload.artifact_type, scope=payload.scope,
        material_ids=payload.material_ids, mode=payload.mode, count=payload.count,
    )


@router.get("")
def list_artifacts(subject_id: UUID, artifact_type: str | None = None,
                   current_user: CurrentUser = Depends(get_current_user)):
    return artifact_service.list_artifacts(
        user_id=current_user.id, subject_id=str(subject_id), artifact_type=artifact_type,
    )


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return artifact_service.get_artifact(user_id=current_user.id, artifact_id=artifact_id)


@router.patch("/{artifact_id}")
def update_artifact(artifact_id: str, payload: ArtifactUpdateRequest,
                    current_user: CurrentUser = Depends(get_current_user)):
    return artifact_service.update_artifact(
        user_id=current_user.id, artifact_id=artifact_id,
        title=payload.title, content=payload.content,
    )


@router.post("/{artifact_id}/flashcards/reviews")
def review_flashcard(artifact_id: str, payload: FlashcardReview,
                     current_user: CurrentUser = Depends(get_current_user)):
    return artifact_service.record_flashcard_review(
        user_id=current_user.id, artifact_id=artifact_id,
        card_id=payload.card_id, rating=payload.rating,
        response_seconds=payload.response_seconds,
    )


@router.get("/{artifact_id}/export")
def export_artifact(artifact_id: str, format: str = Query("json"),
                    current_user: CurrentUser = Depends(get_current_user)):
    data, media_type, filename = artifact_service.export_artifact(
        user_id=current_user.id, artifact_id=artifact_id, export_format=format.lower(),
    )
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
