import asyncio
from datetime import datetime, timezone

import pytest

from app.agents import planner
from app.schemas.closure import ClosureItem, ClosureOutput
from app.schemas.common import AgentEnvelope, AgentMeta, AgentTrace
from app.schemas.planning import PlanningOutput, TomorrowItem


def _closure_envelope():
    return AgentEnvelope(
        meta=AgentMeta(agent_name="closure_agent", run_id="r1", model="test", attempt=1),
        data=ClosureOutput(items=[ClosureItem(id="c1", content="提交报告", category="unfinished", evidence="我还没提交报告", confidence=.9, user_commitment=True)], overall_summary="1 open loop"),
        confidence=.9,
    )


def test_planner_consumes_closure_and_preserves_source_dependency(monkeypatch):
    async def fake_invoke(**kwargs):
        assert kwargs["input_refs"] == ["closure_result"]
        output = PlanningOutput(tomorrow_items=[TomorrowItem(id="p1", source_item_id="c1", title="报告", next_action="检查并提交", priority="medium", blocked=False, suggested_period="morning", confidence=.9)], planning_summary="one action")
        return AgentEnvelope(meta=AgentMeta(agent_name="planning_agent", run_id="r1", model="test", attempt=1), data=output, confidence=.9), AgentTrace(agent="planning_agent", started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc), duration_ms=1, attempt=1, input_refs=["closure_result"], output_schema="PlanningOutput", status="success")

    monkeypatch.setattr(planner, "invoke_structured_agent", fake_invoke)
    result = asyncio.run(planner.planning_node({"run_id": "r1", "closure_result": _closure_envelope()}))
    assert result["planning_result"].data.tomorrow_items[0].source_item_id == "c1"


def test_planner_rejects_invented_closure_source(monkeypatch):
    async def fake_invoke(**kwargs):
        output = PlanningOutput(tomorrow_items=[TomorrowItem(id="p1", source_item_id="invented", title="凭空任务", next_action="做它", priority="high", blocked=False, suggested_period="morning", confidence=.9)], planning_summary="bad")
        return AgentEnvelope(meta=AgentMeta(agent_name="planning_agent", run_id="r1", model="test", attempt=1), data=output, confidence=.9), AgentTrace(agent="planning_agent", started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc), duration_ms=1, attempt=1, input_refs=[], output_schema="PlanningOutput", status="success")

    monkeypatch.setattr(planner, "invoke_structured_agent", fake_invoke)
    with pytest.raises(ValueError, match="invalid source_item_id"):
        asyncio.run(planner.planning_node({"run_id": "r1", "closure_result": _closure_envelope()}))
