from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from uuid import UUID
from typing import Literal

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


class MindMapTopicBinding(BaseModel):
    model_config = {'extra': 'forbid'}
    topic_id: UUID | None = Field(default=None, alias='topicId')
    artifact_version: int = Field(ge=1, alias='artifactVersion')
    binding_version: int = Field(ge=0, alias='bindingVersion')


@router.get('/{artifact_id}/learning')
def map_learning(artifact_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.mind_map_topic_service import learning
    return learning(user_id=user.id, artifact_id=str(artifact_id))


@router.put('/{artifact_id}/nodes/{node_id}/topic')
def bind_map_topic(artifact_id: UUID, node_id: str, payload: MindMapTopicBinding, user: CurrentUser = Depends(get_current_user)):
    from app.services.mind_map_topic_service import bind
    return bind(user_id=user.id, artifact_id=str(artifact_id), node_id=node_id,
                topic_id=str(payload.topic_id) if payload.topic_id else None,
                artifact_version=payload.artifact_version, binding_version=payload.binding_version)


class FlashcardReview(BaseModel):
    card_id: str = Field(min_length=1, max_length=300, validation_alias="cardId")
    rating: Literal["again", "hard", "good", "easy"]
    response_seconds: float | None = Field(default=None, ge=0, le=86400, validation_alias="responseSeconds")
    request_id: UUID | None = Field(default=None, validation_alias="requestId")
    version: int | None = Field(default=None, ge=0)


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
        version=payload.version,
    )


@router.post("/{artifact_id}/flashcards/reviews")
def review_flashcard(artifact_id: str, payload: FlashcardReview,
                     current_user: CurrentUser = Depends(get_current_user)):
    return artifact_service.record_flashcard_review(
        user_id=current_user.id, artifact_id=artifact_id,
        card_id=payload.card_id, rating=payload.rating,
        response_seconds=payload.response_seconds,
        request_id=str(payload.request_id) if payload.request_id else None, version=payload.version,
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
