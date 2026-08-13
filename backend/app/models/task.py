from typing import Literal

from pydantic import BaseModel, Field

TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TaskStage = Literal["queued", "parsing", "embedding", "indexing", "ready", "failed", "cancelled"]


class ProcessingTask(BaseModel):
    id: str
    subject_id: str = Field(serialization_alias="subjectId")
    material_id: str | None = Field(default=None, serialization_alias="materialId")
    task_type: str = Field(serialization_alias="taskType")
    status: TaskStatus
    stage: TaskStage
    progress: int
    attempts: int
    max_attempts: int = Field(serialization_alias="maxAttempts")
    error_code: str | None = Field(default=None, serialization_alias="errorCode")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")
    metadata: dict = Field(default_factory=dict)
    created_at: str | None = Field(default=None, serialization_alias="createdAt")
    updated_at: str | None = Field(default=None, serialization_alias="updatedAt")
