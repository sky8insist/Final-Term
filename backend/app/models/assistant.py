from typing import Literal

from pydantic import BaseModel, Field

AssistantIntent = Literal[
    "qa", "explain_concept", "summarize", "analyze_table", "explain_chart",
    "derive_formula", "compare", "generate_outline", "generate_mind_map",
    "generate_flashcards", "generate_practice", "generate_exam", "grade_answer",
    "review_wrong_answers", "build_study_plan", "show_progress", "external_research",
]
TutorRole = Literal["auto", "beginner", "crash_course", "socratic", "examiner", "mistake_coach", "academic", "sprint_planner"]


class AssistantMessageRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(validation_alias="sessionId")
    role: TutorRole = "auto"
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    allow_external_knowledge: bool = Field(default=False, validation_alias="allowExternalKnowledge")


class IntentDecision(BaseModel):
    primary_intent: AssistantIntent = Field(serialization_alias="primaryIntent")
    secondary_intents: list[AssistantIntent] = Field(default_factory=list, serialization_alias="secondaryIntents")
    confidence: float = Field(ge=0, le=1)
    needs_retrieval: bool = Field(serialization_alias="needsRetrieval")
    needs_clarification: bool = Field(serialization_alias="needsClarification")
    clarification_question: str | None = Field(default=None, serialization_alias="clarificationQuestion")
    required_skills: list[str] = Field(default_factory=list, serialization_alias="requiredSkills")
    material_scope: dict = Field(default_factory=dict, serialization_alias="materialScope")
    allow_external_knowledge: bool = Field(default=False, serialization_alias="allowExternalKnowledge")
