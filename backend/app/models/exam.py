from typing import Literal

from pydantic import BaseModel, Field, model_validator

QuestionType = Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "calculation", "essay"]
Difficulty = Literal["easy", "medium", "hard"]
AssessmentType = Literal["practice", "stage", "mock"]


class QuestionTypeSpec(BaseModel):
    question_type: QuestionType = Field(validation_alias="questionType")
    count: int = Field(ge=1, le=100)
    points_each: float = Field(gt=0, le=100, validation_alias="pointsEach")


class ExamGenerateRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    title: str = Field(default="期末模拟试卷", min_length=1, max_length=300)
    duration_minutes: int = Field(default=90, ge=1, le=1440, validation_alias="durationMinutes")
    difficulty: Difficulty = "medium"
    question_types: list[QuestionTypeSpec] = Field(validation_alias="questionTypes")
    scope: str | None = Field(default=None, max_length=1000)
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    external_ratio: float = Field(default=0, ge=0, le=1, validation_alias="externalRatio")
    avoid_seen: bool = Field(default=True, validation_alias="avoidSeen")
    assessment_type: AssessmentType = Field(default="mock", validation_alias="assessmentType")

    @model_validator(mode="after")
    def question_limit(self):
        if sum(item.count for item in self.question_types) > 100:
            raise ValueError("Exam cannot contain more than 100 questions")
        return self


class StartAttemptRequest(BaseModel):
    exam_id: str = Field(validation_alias="examId")


class SaveResponseRequest(BaseModel):
    question_id: str = Field(validation_alias="questionId")
    response: object
