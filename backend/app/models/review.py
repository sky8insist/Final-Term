from pydantic import BaseModel, Field


class ReviewProgress(BaseModel):
    subject_id: str = Field(serialization_alias="subjectId")
    mastered_count: int = Field(default=0, serialization_alias="masteredCount")
    total_count: int = Field(default=0, serialization_alias="totalCount")
    updated_at: str | None = Field(default=None, serialization_alias="updatedAt")


class ReviewProgressUpdate(BaseModel):
    mastered_count: int | None = Field(default=None, validation_alias="masteredCount")
    total_count: int | None = Field(default=None, validation_alias="totalCount")
