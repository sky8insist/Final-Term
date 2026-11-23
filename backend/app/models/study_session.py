from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SessionCreate(SessionModel):
    request_id: UUID = Field(alias="requestId")
    subject_id: UUID = Field(alias="subjectId")
    knowledge_point_id: UUID = Field(alias="knowledgePointId")
    exam_event_id: UUID | None = Field(default=None, alias="examEventId")
    recommendation_id: UUID | None = Field(default=None, alias="recommendationId")
    minutes: int = Field(default=30, ge=10, le=120)


class StepPlan(SessionModel):
    kind: Literal["notes", "socratic", "flashcards", "quiz", "mastery_check"]
    estimated_minutes: int = Field(alias="estimatedMinutes", ge=1, le=60)


class SessionAction(SessionModel):
    version: int = Field(ge=1)
    action: Literal["accept", "edit", "execute", "complete", "skip", "cancel"]
    steps: list[StepPlan] | None = Field(default=None, min_length=2, max_length=8)
    attempt_id: UUID | None = Field(default=None, alias="attemptId")

    @model_validator(mode="after")
    def valid_plan(self):
        if self.action == "edit":
            if not self.steps or self.steps[-1].kind != "mastery_check" or sum(s.kind == "quiz" for s in self.steps) != 1:
                raise ValueError("计划必须包含一次测验，并以掌握度检查结束")
            if any(s.kind == "mastery_check" for s in self.steps[:-1]):
                raise ValueError("掌握度检查只能放在最后")
        elif self.steps is not None:
            raise ValueError("只有编辑计划时可以修改步骤")
        return self


class SessionMessage(SessionModel):
    message: str = Field(min_length=1, max_length=4000)
