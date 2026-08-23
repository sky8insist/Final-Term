from typing import Literal

from pydantic import BaseModel, Field

ArtifactType = Literal["outline", "mind_map", "flashcards", "formula_sheet", "glossary", "comparison", "cheat_sheet"]


class ArtifactGenerateRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    artifact_type: ArtifactType = Field(validation_alias="artifactType")
    scope: str | None = Field(default=None, max_length=1000)
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    mode: str | None = None
    count: int = Field(default=20, ge=1, le=100)


class ArtifactScopedGenerateRequest(BaseModel):
    """Payload for typed convenience endpoints such as /mind-maps."""

    subject_id: str = Field(validation_alias="subjectId")
    scope: str | None = Field(default=None, max_length=1000)
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    mode: str | None = None
    count: int = Field(default=20, ge=1, le=100)


MindMapMode = Literal["question", "topic", "chapter"]


class MindMapGenerateRequest(BaseModel):
    """Question-driven knowledge-map request used by the dedicated workflow."""

    subject_id: str = Field(validation_alias="subjectId")
    mode: MindMapMode = "question"
    query: str | None = Field(default=None, max_length=1000)
    topic_id: str | None = Field(default=None, validation_alias="topicId", max_length=300)
    chapter_id: str | None = Field(default=None, validation_alias="chapterId", max_length=300)
    max_depth: int = Field(default=3, ge=2, le=4, validation_alias="maxDepth")
    include_mastery: bool = Field(default=True, validation_alias="includeMastery")
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    count: int = Field(default=24, ge=4, le=40)


class ArtifactUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: dict | None = None
