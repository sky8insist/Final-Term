"""Run real SiliconFlow structured-output checks for every Dayend V3 agent.

This script never enables mocks or hides failures. It emits one JSON record per
independent invocation, including latency and provider-reported token usage when
available. Missing usage remains null rather than being reported as zero.
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.closure import closure_node
from app.agents.critic import critic_node
from app.agents.emotion import emotion_node
from app.agents.morning import morning_node
from app.agents.planner import planning_node
from app.agents.safety import safety_node
from app.agents.supervisor import supervisor_node
from app.config.settings import settings
from app.schemas.common import AgentRunFailed


def _record(trace: Any, envelope: Any | None = None, *, status: str = "PASS", error: str | None = None) -> None:
    print(json.dumps({
        "acceptance": status,
        "agent": trace.agent if trace else None,
        "schema": trace.output_schema if trace else None,
        "model": getattr(getattr(envelope, "meta", None), "model", None),
        "attempt": trace.attempt if trace else None,
        "duration_ms": trace.duration_ms if trace else None,
        "token_usage": trace.token_usage if trace else None,
        "trace_status": trace.status if trace else "failed",
        "error": error,
    }, ensure_ascii=False))


async def _run(name: str, node: Any, state: dict[str, Any], output_key: str) -> dict[str, Any] | None:
    try:
        result = await node(state)
        trace = result["agent_trace"][-1]
        envelope = result.get(output_key)
        _record(trace, envelope)
        return result
    except AgentRunFailed as exc:
        _record(exc.trace, status="FAILED_NO_FALLBACK", error=f"{name}: {exc}")
    except Exception as exc:
        _record(None, status="FAILED", error=f"{name}: {exc}")
    return None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--critic-only", action="store_true")
    args = parser.parse_args()
    settings.dayend_max_retries = 0
    state: dict[str, Any] = {
        "run_id": "live-all-agents-acceptance",
        "thread_id": "live-all-agents-thread",
        "user_input": "今天完成了报告初稿，但还没有发给导师；我担心反馈会不好，所以有点焦虑。",
        "entry_point": "night",
        "current_session_summary": "",
        "critic_feedback": {},
        "human_response": {"confirmed": True},
    }
    if args.critic_only:
        state.update({
            "closure_result": {"items": [{"id": "c1", "content": "Send report", "category": "unfinished", "evidence": "not sent", "confidence": .9, "user_commitment": True}], "overall_summary": "Report remains unsent.", "needs_confirmation_ids": []},
            "planning_result": {"tomorrow_items": [{"id": "p1", "source_item_id": "c1", "title": "Send report", "next_action": "Review and send it", "priority": "high", "blocked": False, "suggested_period": "morning", "estimated_minutes": 20, "confidence": .9}], "deferred_items": [], "planning_summary": "Send the report."},
            "emotion_result": {"events": ["Completed draft"], "expressed_emotions": ["worried"], "unresolved_thoughts": ["feedback"], "reflection_summary": "Worried about feedback.", "inferred_content": [], "confidence": .9},
            "safety_result": {"level": "low", "evidence": ["worry"], "immediate_response_required": False, "suppress_delayed_only_response": False, "response_strategy": "supportive", "confidence": .9},
        })
        await _run("critic_agent", critic_node, state, "critic_result")
        return
    supervisor = await _run("supervisor_agent", supervisor_node, state, "supervisor_result")
    if supervisor:
        state.update(supervisor)
    closure = await _run("closure_agent", closure_node, state, "closure_result")
    if closure:
        state.update(closure)
        planning = await _run("planning_agent", planning_node, state, "planning_result")
        if planning:
            state.update(planning)
    emotion = await _run("emotion_agent", emotion_node, state, "emotion_result")
    if emotion:
        state.update(emotion)
        safety = await _run("safety_agent", safety_node, state, "safety_result")
        if safety:
            state.update(safety)
    if state.get("closure_result") or state.get("emotion_result"):
        critic = await _run("critic_agent", critic_node, state, "critic_result")
        if critic:
            state.update(critic)
    await _run("morning_agent", morning_node, state, "final_output")


if __name__ == "__main__":
    asyncio.run(main())
