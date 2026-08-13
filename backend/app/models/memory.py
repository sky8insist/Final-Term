from typing import Literal

from pydantic import BaseModel, Field

MemoryTarget = Literal["assistant_memory", "user_profile"]
MemoryAction = Literal["add", "replace", "remove"]


class MemoryWrite(BaseModel):
    action: MemoryAction
    target: MemoryTarget
    subject_id: str | None = Field(default=None, validation_alias="subjectId")
    old_text: str | None = Field(default=None, validation_alias="oldText")
    content: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    importance: int = Field(default=50, ge=0, le=100)
    reason: str | None = None
    require_approval: bool | None = Field(default=None, validation_alias="requireApproval")


class LearnerProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, validation_alias="displayName", max_length=100)
    timezone: str | None = Field(default=None, max_length=80)
    level: Literal["beginner", "intermediate", "advanced"] | None = None
    preferred_role: str | None = Field(default=None, validation_alias="preferredRole", max_length=60)
    response_style: Literal["concise", "balanced", "detailed"] | None = Field(default=None, validation_alias="responseStyle")
    daily_minutes: int | None = Field(default=None, ge=5, le=1440, validation_alias="dailyMinutes")
    exam_date: str | None = Field(default=None, validation_alias="examDate")
    memory_enabled: bool | None = Field(default=None, validation_alias="memoryEnabled")
    write_approval: bool | None = Field(default=None, validation_alias="writeApproval")
