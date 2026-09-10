import asyncio
from datetime import datetime, timezone

from app.agents import supervisor
from app.schemas.common import AgentEnvelope, AgentMeta, AgentTrace
from app.schemas.supervisor import AgentStep, SupervisorOutput


def test_supervisor_is_an_independent_structured_invocation(monkeypatch):
    async def fake_invoke(**kwargs):
        assert kwargs["agent_name"] == "supervisor_agent"
        assert kwargs["schema"] is SupervisorOutput
        assert {tool.name for tool in kwargs["tools"]} == {
            "get_current_session_state", "get_last_closure_status",
        }
        output = SupervisorOutput(
            primary_intent="day_closure",
            execution_plan=[AgentStep(agent="closure_agent", reason="The input asks to close the day")],
            confidence=0.9,
        )
        return (
            AgentEnvelope(meta=AgentMeta(agent_name="supervisor_agent", run_id="r1", model="test", attempt=1), data=output, confidence=0.9),
            AgentTrace(agent="supervisor_agent", started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc), duration_ms=1, attempt=1, input_refs=["user_input"], output_schema="SupervisorOutput", status="success"),
        )

    monkeypatch.setattr(supervisor, "invoke_structured_agent", fake_invoke)
    result = asyncio.run(supervisor.supervisor_node({
        "run_id": "r1", "thread_id": "t1", "user_input": "今天收尾一下", "entry_point": "night",
    }))
    assert result["supervisor_result"].data.primary_intent == "day_closure"
    assert result["agent_trace"][0].agent == "supervisor_agent"
