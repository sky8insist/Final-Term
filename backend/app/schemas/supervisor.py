from typing import Literal

from pydantic import BaseModel, Field


AgentName = Literal[
    "closure_agent", "planning_agent", "emotion_agent", "safety_agent", "critic_agent"
]


class AgentStep(BaseModel):
    agent: AgentName
    reason: str = Field(min_length=1)
    depends_on: list[AgentName] = Field(default_factory=list)


class SupervisorOutput(BaseModel):
    primary_intent: Literal["day_closure", "emotion_release", "mixed", "morning_review", "unknown"]
    secondary_intents: list[str] = Field(default_factory=list)
    execution_plan: list[AgentStep] = Field(default_factory=list)
    needs_human_confirmation: bool = False
    confidence: float = Field(ge=0, le=1)
