from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.models.course import CourseModel, UnitCreate


class ExamTopic(CourseModel):
    knowledge_point_id: UUID
    weight: float = Field(default=1, ge=0, le=100)


class ExamEventSave(UnitCreate):
    exam_date: date
    syllabus_id: UUID | None = None
    status: Literal["active", "completed", "archived"] = "active"
    topics: list[ExamTopic] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_topics(self):
        if len({item.knowledge_point_id for item in self.topics}) != len(self.topics):
            raise ValueError("考试范围不能包含重复知识点")
        if not any(item.weight > 0 for item in self.topics):
            raise ValueError("至少一个知识点需要正权重")
        return self


class SyllabusCreate(UnitCreate):
    content: dict = Field(default_factory=dict)
    topic_ids: list[UUID] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_topics(self):
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("大纲不能包含重复知识点")
        return self
