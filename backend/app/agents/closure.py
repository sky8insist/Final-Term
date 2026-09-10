from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.closure import ClosureOutput
from app.state.dayend_state import DayendState


PROMPT = """You are the Closure Agent. Extract only explicitly grounded end-of-day items.
Classify each as completed, unfinished, waiting, or uncertain. Every item needs verbatim
or close evidence from the user's input. Do not create tomorrow actions, priorities, advice,
or unexpressed tasks. Return the ClosureOutput schema."""


async def closure_node(state: DayendState) -> dict:
    feedback = (state.get("critic_feedback") or {}).get("closure_agent", [])
    envelope, trace = await invoke_structured_agent(
        agent_name="closure_agent", schema=ClosureOutput, system_prompt=PROMPT,
        user_prompt=state["user_input"] + ("\n\nCritic revision feedback:\n- " + "\n- ".join(feedback) if feedback else ""),
        run_id=state["run_id"], input_refs=["user_input"] + (["critic_feedback"] if feedback else []),
    )
    if feedback:
        trace = trace.model_copy(update={"status": "revision"})
    pending = [
        item.model_dump(mode="json") for item in envelope.data.items
        if item.id in envelope.data.needs_confirmation_ids
    ]
    return {"closure_result": envelope, "pending_confirmation": pending, "agent_trace": [trace]}
