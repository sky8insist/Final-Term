import json

from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.closure import ClosureOutput
from app.schemas.planning import PlanningOutput
from app.state.dayend_state import DayendState


PROMPT = """You are the Planning Agent. Consume the supplied ClosureOutput only. Create a
tomorrow item only for a valid unfinished/waiting closure item and retain its source_item_id.
Do not re-extract the input or invent tasks. If an item is blocked, make its next_action a
small step toward removing the blocker. Return the PlanningOutput schema."""


async def planning_node(state: DayendState) -> dict:
    closure = state.get("closure_result")
    if closure is None:
        raise ValueError("planning_agent requires closure_result")
    data = closure.data if hasattr(closure, "data") else ClosureOutput.model_validate(closure)
    feedback = (state.get("critic_feedback") or {}).get("planning_agent", [])
    envelope, trace = await invoke_structured_agent(
        agent_name="planning_agent", schema=PlanningOutput, system_prompt=PROMPT,
        user_prompt=json.dumps({"closure": data.model_dump(mode="json"), "critic_feedback": feedback}, ensure_ascii=False), run_id=state["run_id"],
        input_refs=["closure_result"] + (["critic_feedback"] if feedback else []),
    )
    valid_ids = {item.id for item in data.items}
    invalid = [item.source_item_id for item in envelope.data.tomorrow_items if item.source_item_id not in valid_ids]
    if invalid:
        raise ValueError(f"planning_agent created invalid source_item_id values: {invalid}")
    if feedback:
        trace = trace.model_copy(update={"status": "revision"})
    return {"planning_result": envelope, "agent_trace": [trace]}
