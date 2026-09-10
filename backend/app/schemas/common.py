from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class AgentMeta(BaseModel):
    agent_name: str
    run_id: str
    schema_version: Literal["3.0"] = "3.0"
    model: str
    attempt: int = Field(ge=1)


class AgentEnvelope(BaseModel, Generic[T]):
    meta: AgentMeta
    data: T
    confidence: float = Field(ge=0, le=1)


class AgentTrace(BaseModel):
    agent: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int = Field(ge=0)
    attempt: int = Field(ge=1)
    input_refs: list[str] = Field(default_factory=list)
    output_schema: str
    tool_calls: list[str] = Field(default_factory=list)
    status: Literal["success", "failed", "revision"]
    token_usage: dict | None = None
    failure_type: str | None = None


class AgentRunFailed(RuntimeError):
    """An agent exhausted its provider/schema retries in multi-agent mode."""

    def __init__(self, message: str, *, trace: AgentTrace | None = None, failure_type: str | None = None):
        super().__init__(message)
        self.trace = trace
        self.failure_type = failure_type
