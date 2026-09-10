from typing import Literal

from pydantic import BaseModel, Field


class SafetyAssessment(BaseModel):
    level: Literal["none", "low", "elevated", "urgent"]
    evidence: list[str] = Field(default_factory=list)
    immediate_response_required: bool
    suppress_delayed_only_response: bool
    response_strategy: Literal["normal", "supportive", "urgent_support"]
    confidence: float = Field(ge=0, le=1)
