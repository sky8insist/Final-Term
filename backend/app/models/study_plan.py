from pydantic import BaseModel, Field


class StudyPlanRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    exam_date: str = Field(validation_alias="examDate")
    daily_minutes: int = Field(default=60, ge=5, le=1440, validation_alias="dailyMinutes")
    title: str = Field(default="期末复习计划", min_length=1, max_length=300)


class ReviewTaskUpdate(BaseModel):
    status: str | None = None
    scheduled_date: str | None = Field(default=None, validation_alias="scheduledDate")
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440, validation_alias="estimatedMinutes")
