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


class ArtifactUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: dict | None = None
