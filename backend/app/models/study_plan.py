from pydantic import BaseModel, ConfigDict, Field


class StudyPlanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subject_id: str = Field(validation_alias="subjectId")
    exam_date: str = Field(validation_alias="examDate")
    daily_minutes: int = Field(default=60, ge=15, le=720, validation_alias="dailyMinutes")
    weekend_extra: bool = Field(default=False, validation_alias="weekendExtra")
    reserve_final_day: bool = Field(default=True, validation_alias="reserveFinalDay")
    preserve_existing: bool = Field(default=True, validation_alias="preserveExisting")
    title: str = Field(default="目标日期复习计划", min_length=1, max_length=300)


class ReviewTaskUpdate(BaseModel):
    status: str | None = None
    scheduled_date: str | None = Field(default=None, validation_alias="scheduledDate")
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440, validation_alias="estimatedMinutes")
