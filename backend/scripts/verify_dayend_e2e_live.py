"""Real Dayend V3 graph acceptance checks; never substitutes mocked agents."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import settings
from app.agents.critic import critic_node
from app.agents.planner import planning_node
from app.graphs.mixed_graph import build_mixed_graph
from app.graphs.revision import prepare_revision
from app.schemas.common import AgentRunFailed


def merge_update(state: dict, update: dict) -> None:
    """Apply node output while preserving every independently emitted trace."""
    traces = list(state.get("agent_trace", [])) + list(update.get("agent_trace", []))
    state.update({key: value for key, value in update.items() if key != "agent_trace"})
    state["agent_trace"] = traces


async def verify_mixed() -> None:
    thread_id = f"live-mixed-{uuid4()}"
    state = {
        "run_id": f"live-mixed-{uuid4()}", "thread_id": thread_id,
        "user_id": "live-acceptance", "entry_point": "night",
        "user_input": (
            "I finished the report draft but have not sent it to my advisor. "
            "I am worried about the feedback and want a small next step for tomorrow."
        ),
        "current_session_summary": "", "revision_count": {}, "critic_feedback": {},
        "pending_confirmation": [], "agent_trace": [],
    }
    try:
        result = await build_mixed_graph(with_checkpointer=False).ainvoke(state)
        traces = result.get("agent_trace", [])
        agents = [trace.agent for trace in traces]
        required = {"closure_agent", "planning_agent", "emotion_agent", "safety_agent", "critic_agent"}
        print(json.dumps({
            "acceptance": "PASS" if required <= set(agents) else "FAILED",
            "case": "mixed_graph", "agents": agents,
            "trace": [trace.model_dump(mode="json") for trace in traces],
            "critic_passed": getattr(getattr(result.get("critic_result"), "data", None), "passed", None),
        }, ensure_ascii=False))
    except AgentRunFailed as exc:
        print(json.dumps({"acceptance": "FAILED_NO_FALLBACK", "case": "mixed_graph", "trace": exc.trace.model_dump(mode="json") if exc.trace else None, "failure_type": exc.failure_type, "error": str(exc)}))


async def verify_revision() -> None:
    state = {
        "run_id": f"live-revision-{uuid4()}",
        "user_input": "I finished a report draft but have not sent it to my advisor.",
        "closure_result": {"items": [{"id": "c1", "content": "Send report", "category": "unfinished", "evidence": "have not sent it", "confidence": .9, "user_commitment": True}], "overall_summary": "Sending remains open.", "needs_confirmation_ids": []},
        # Deliberately unsupported content must be rejected by a real Critic.
        "planning_result": {"tomorrow_items": [{"id": "p1", "source_item_id": "c1", "title": "Prepare for an English exam", "next_action": "Study English grammar", "priority": "high", "blocked": False, "suggested_period": "morning", "estimated_minutes": 30, "confidence": .9}], "deferred_items": [], "planning_summary": "Prepare for the English exam."},
        "critic_feedback": {}, "revision_count": {}, "agent_trace": [],
    }
    try:
        initial = await critic_node(state)
        merge_update(state, initial)
        revision = prepare_revision(state)
        merge_update(state, revision)
        if revision.get("revision_target") != "planning_agent":
            print(json.dumps({"acceptance": "NOT_TRIGGERED", "case": "critic_revision", "target": revision.get("revision_target"), "trace": [trace.model_dump(mode="json") for trace in state["agent_trace"]]}))
            return
        revised = await planning_node(state)
        merge_update(state, revised)
        final = await critic_node(state)
        merge_update(state, final)
        print(json.dumps({
            "acceptance": "PASS" if state["critic_result"].data.passed else "FAILED",
            "case": "critic_revision", "revision_target": revision["revision_target"],
            "revision_count": state["revision_count"],
            "trace": [trace.model_dump(mode="json") for trace in state["agent_trace"]],
        }, ensure_ascii=False))
    except AgentRunFailed as exc:
        print(json.dumps({"acceptance": "FAILED_NO_FALLBACK", "case": "critic_revision", "trace": exc.trace.model_dump(mode="json") if exc.trace else None, "failure_type": exc.failure_type, "error": str(exc)}))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["mixed", "revision"], default="mixed")
    args = parser.parse_args()
    settings.dayend_max_retries = 1 if args.case == "revision" else 0
    if args.case == "mixed":
        await verify_mixed()
    else:
        await verify_revision()


if __name__ == "__main__":
    asyncio.run(main())
