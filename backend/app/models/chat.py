from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator


class Citation(BaseModel):
    id: str
    material_id: str = Field(
        validation_alias=AliasChoices("materialId", "material_id"),
        serialization_alias="materialId",
    )
    source_name: str = Field(
        validation_alias=AliasChoices("sourceName", "source_name"),
        serialization_alias="sourceName",
    )
    text: str
    score: float | None = None
    source_type: Literal["material", "external"] = Field(default="material", serialization_alias="sourceType")
    url: str | None = None
    title: str | None = None
    accessed_at: str | None = Field(default=None, serialization_alias="accessedAt")
    trust_level: str | None = Field(default=None, serialization_alias="trustLevel")
    block_type: str | None = Field(default=None, serialization_alias="blockType")
    page_number: int | None = Field(default=None, serialization_alias="pageNumber")
    start_time: float | None = Field(default=None, serialization_alias="startTime")
    end_time: float | None = Field(default=None, serialization_alias="endTime")
    retrieval_source: str | None = Field(default=None, serialization_alias="retrievalSource")
    bounding_box: dict | None = Field(default=None, serialization_alias="boundingBox")
    structured_data: dict | None = Field(default=None, serialization_alias="structuredData")


class ChatRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    question: str = Field(max_length=4000)
    session_id: str | None = Field(default=None, validation_alias="sessionId")
    mode: Literal["detail", "quick", "socratic", "exam"] = "detail"

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question is required")
        return cleaned


class ChatMessage(BaseModel):
    id: str
    subject_id: str = Field(serialization_alias="subjectId")
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = []
    created_at: str | None = Field(default=None, serialization_alias="createdAt")


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    message_id: str = Field(serialization_alias="messageId")
