from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CourseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnitCreate(CourseModel):
    title: str = Field(min_length=1, max_length=300)
    sequence_index: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class TopicCreate(UnitCreate):
    unit_id: UUID | None = None
    syllabus_weight: float = Field(default=1, ge=0, le=100)
    source_refs: list[dict] = Field(default_factory=list, max_length=200)


class TopicUpdate(CourseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    unit_id: UUID | None = None
    sequence_index: int | None = Field(default=None, ge=0)
    syllabus_weight: float | None = Field(default=None, ge=0, le=100)
    archived: bool | None = None

    @field_validator("title", "sequence_index", "syllabus_weight", "archived")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("字段不能为 null")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("名称不能为空")
        return value
