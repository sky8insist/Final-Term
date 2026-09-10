from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CriticIssue(BaseModel):
    issue_type: Literal["hallucination", "unsupported_inference", "missing_item", "role_violation", "contradiction", "low_actionability"]
    target_agent: Literal["closure_agent", "planning_agent", "emotion_agent", "safety_agent"]
    severity: Literal["low", "medium", "high"]
    message: str


class CriticOutput(BaseModel):
    passed: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    revision_targets: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def failed_reviews_must_name_their_revision_targets(self):
        if self.passed:
            return self
        issue_targets = {issue.target_agent for issue in self.issues}
        if not issue_targets:
            raise ValueError("a failed review must contain at least one issue")
        # The Critic's semantic targets are the target_agent values on issues.
        # Project them once for graph routing rather than accepting a second,
        # redundant model-generated list that may contradict those issues.
        self.revision_targets = sorted(issue_targets)
        return self
