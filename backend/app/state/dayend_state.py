from typing import Annotated, Any, TypedDict

from app.schemas.common import AgentEnvelope, AgentTrace
from app.schemas.supervisor import SupervisorOutput


def append_trace(existing: list[AgentTrace] | None, incoming: list[AgentTrace] | None) -> list[AgentTrace]:
    return (existing or []) + (incoming or [])


class DayendState(TypedDict, total=False):
    thread_id: str
    run_id: str
    user_id: str | None
    user_input: str
    entry_point: str
    timestamp: str
    current_session_summary: str | None
    supervisor_result: AgentEnvelope[SupervisorOutput] | None
    closure_result: Any
    planning_result: Any
    emotion_result: Any
    safety_result: Any
    guardrail_result: dict | None
    critic_result: Any
    revision_count: dict[str, int]
    revision_target: str | None
    critic_feedback: dict[str, list[str]]
    pending_confirmation: list[dict]
    human_response: dict | None
    final_output: dict | None
    agent_trace: Annotated[list[AgentTrace], append_trace]
