from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionType = Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "calculation", "essay"]
Difficulty = Literal["easy", "medium", "hard"]
AssessmentType = Literal["practice", "stage", "mock"]
KnowledgePolicy = Literal["course_only", "course_first", "expanded"]


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class QuestionTypeSpec(ApiModel):
    question_type: QuestionType = Field(alias="questionType")
    count: int = Field(ge=0, le=100)
    points_each: float = Field(gt=0, le=100, alias="pointsEach")


class ExamGenerateRequest(ApiModel):
    subject_id: str = Field(alias="subjectId")
    title: str = Field(default="期末模拟试卷", min_length=1, max_length=300)
    duration_minutes: int = Field(default=90, ge=1, le=1440, alias="durationMinutes")
    difficulty: Difficulty = "medium"
    question_types: list[QuestionTypeSpec] = Field(alias="questionTypes")
    scope: str | None = Field(default=None, max_length=1000)
    material_ids: list[str] | None = Field(default=None, alias="materialIds")
    external_ratio: float = Field(default=0, ge=0, le=1, alias="externalRatio")
    knowledge_policy: KnowledgePolicy | None = Field(default=None, alias="knowledgePolicy")
    avoid_seen: bool = Field(default=True, alias="avoidSeen")
    assessment_type: AssessmentType = Field(default="mock", alias="assessmentType")

    @model_validator(mode="after")
    def question_limit(self):
        if self.knowledge_policy is None:
            self.knowledge_policy = "course_first" if self.assessment_type == "practice" else "course_only"
        if self.assessment_type == "practice":
            self.scope = (self.scope or "").strip()
            if not self.scope:
                raise ValueError("Practice topic is required")
        question_count = sum(item.count for item in self.question_types)
        if question_count < 1:
            raise ValueError("Exam must contain at least one question")
        if question_count > 100:
            raise ValueError("Exam cannot contain more than 100 questions")
        return self


class StartAttemptRequest(ApiModel):
    exam_id: str = Field(alias="examId")


class SaveResponseRequest(ApiModel):
    question_id: str = Field(alias="questionId")
    response: object


class ConfirmResponseRequest(ApiModel):
    response: object
