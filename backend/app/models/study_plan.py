from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudyPlanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subject_id: str = Field(validation_alias="subjectId")
    exam_date: str | None = Field(default=None, validation_alias="examDate")
    exam_event_id: UUID | None = Field(default=None, alias="examEventId")
    mode: Literal["CRAM", "STANDARD", "COMPREHENSIVE"] = "STANDARD"
    available_minutes: dict[date, int] = Field(default_factory=dict, alias="availableMinutes")
    auto_replan: bool = Field(default=True, alias="autoReplan")
    daily_minutes: int = Field(default=60, ge=15, le=720, validation_alias="dailyMinutes")
    weekend_extra: bool = Field(default=False, validation_alias="weekendExtra")
    reserve_final_day: bool = Field(default=True, validation_alias="reserveFinalDay")
    preserve_existing: bool = Field(default=True, validation_alias="preserveExisting")
    title: str = Field(default="目标日期复习计划", min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_goal(self):
        if not self.exam_date and not self.exam_event_id: raise ValueError("需要考试目标或目标日期")
        if len(self.available_minutes) > 366 or any(not 0 <= amount <= 720 for amount in self.available_minutes.values()):
            raise ValueError("逐日时间须为 0 到 720 分钟，最多 366 天")
        return self


class ReviewTaskUpdate(BaseModel):
    locked: bool | None = None
    status: str | None = None
    scheduled_date: str | None = Field(default=None, validation_alias="scheduledDate")
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440, validation_alias="estimatedMinutes")
