from typing import Literal

from pydantic import BaseModel, Field

AssistantIntent = Literal[
    "qa", "explain_concept", "summarize", "analyze_table", "explain_chart",
    "derive_formula", "compare", "generate_outline", "generate_mind_map",
    "generate_flashcards", "generate_practice", "generate_exam", "grade_answer",
    "analyze_practice_performance", "build_study_plan", "show_progress", "external_research",
]
TutorRole = Literal["auto", "beginner", "crash_course", "socratic", "examiner", "performance_coach", "academic", "sprint_planner"]
DialogueAct = Literal[
    "answer_to_pending_question", "followup_question_same_topic", "new_question",
    "request_hint", "request_full_solution", "confirmation",
    "challenge_or_correction", "clarification", "meta_command", "ambiguous",
]
KnowledgePolicy = Literal["course_only", "course_first", "expanded"]


class AssistantMessageRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(validation_alias="sessionId")
    role: TutorRole = "auto"
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    allow_external_knowledge: bool = Field(default=False, validation_alias="allowExternalKnowledge")
    knowledge_policy: KnowledgePolicy = Field(default="course_only", validation_alias="knowledgePolicy")
    interaction_id: str | None = Field(default=None, validation_alias="interactionId")
    response_to_message_id: str | None = Field(default=None, validation_alias="responseToMessageId")
    question_id: str | None = Field(default=None, validation_alias="questionId")
    attempt_id: str | None = Field(default=None, validation_alias="attemptId")
    dialogue_act_override: DialogueAct | None = Field(default=None, validation_alias="dialogueActOverride")


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


class DialogueDecision(BaseModel):
    dialogue_act: DialogueAct = Field(serialization_alias="dialogueAct")
    confidence: float = Field(ge=0, le=1)
    target_interaction_id: str | None = Field(default=None, serialization_alias="targetInteractionId")
    related_knowledge_point: str | None = Field(default=None, serialization_alias="relatedKnowledgePoint")
    resolved_question: str | None = Field(default=None, serialization_alias="resolvedQuestion")
    should_retrieve: bool = Field(serialization_alias="shouldRetrieve")
    retrieval_query_source: Literal["none", "current_message", "resolved_question", "original_question"] = Field(
        default="current_message", serialization_alias="retrievalQuerySource",
    )
    reason_code: str = Field(default="classified", serialization_alias="reasonCode")
