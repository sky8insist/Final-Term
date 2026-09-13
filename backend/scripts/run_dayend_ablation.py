"""Run real Dayend A/B/C ablations and emit one auditable JSONL row per run."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.closure import closure_node
from app.agents.critic import critic_node
from app.agents.emotion import emotion_node
from app.agents.planner import planning_node
from app.agents.safety import safety_node
from app.config.settings import settings


async def _node(node, state):
    update = await node(state)
    state.update({key: value for key, value in update.items() if key != "agent_trace"})
    state.setdefault("agent_trace", []).extend(update.get("agent_trace", []))


async def run_case(case: dict, variant: str) -> dict:
    category = case["category"]
    state = {"run_id": str(uuid4()), "thread_id": str(uuid4()), "user_input": case["user_input"],
             "entry_point": "night", "critic_feedback": {}, "revision_count": {}, "agent_trace": []}
    started = perf_counter()
    if variant == "single_agent":
        await _node(emotion_node if category in {"emotion", "safety_critical"} else closure_node, state)
    else:
        if category in {"emotion", "safety_critical"}:
            await _node(emotion_node, state); await _node(safety_node, state)
        elif category == "mixed":
            await _node(closure_node, state); await _node(emotion_node, state)
            await _node(planning_node, state); await _node(safety_node, state)
        else:
            await _node(closure_node, state); await _node(planning_node, state)
        if variant == "full_multi_agent":
            await _node(critic_node, state)
    traces = [trace.model_dump(mode="json") for trace in state["agent_trace"]]
    outputs = {}
    for key in ("closure_result", "planning_result", "emotion_result", "safety_result", "critic_result"):
        value = state.get(key)
        if value is not None:
            outputs[key] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    usage = [trace.get("token_usage") or {} for trace in traces]
    tokens = sum(float(item.get("total_tokens", 0) or 0) for item in usage) if usage else None
    return {"case_id": case["case_id"], "category": category, "variant": variant,
            "simulated": False, "latency_ms": round((perf_counter() - started) * 1000),
            "total_tokens": tokens if usage else None, "token_cost": None, "grounding": None,
            "unsupported_task_rate": None, "actionability": None, "trace": traces,
            "outputs": outputs}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--representative", action="store_true", help="Run the first case from every category")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if settings.dayend_mode != "multi_agent" or settings.mock_external_apis:
        raise RuntimeError("real ablations require DAYEND_MODE=multi_agent and MOCK_EXTERNAL_APIS=false")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.representative:
        selected = {}
        for case in cases:
            selected.setdefault(case["category"], case)
        cases = list(selected.values())
    if args.limit:
        cases = cases[:args.limit]
    completed = set()
    if args.resume and args.output.exists():
        completed = {(row["case_id"], row["variant"]) for line in args.output.read_text(encoding="utf-8").splitlines() if line.strip() for row in [json.loads(line)] if row.get("status") != "failed"}
    with args.output.open("a" if args.resume else "w", encoding="utf-8") as stream:
        for case in cases:
            for variant in ("single_agent", "multi_agent_without_critic", "full_multi_agent"):
                if (case["case_id"], variant) in completed:
                    continue
                try:
                    row = await run_case(case, variant)
                except Exception as exc:
                    row = {"case_id": case["case_id"], "category": case["category"], "variant": variant,
                           "simulated": False, "status": "failed", "error": str(exc)}
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()


if __name__ == "__main__":
    asyncio.run(main())
