from langgraph.types import interrupt

from app.state.dayend_state import DayendState


def human_confirmation_node(state: DayendState) -> dict:
    """Pause at a durable graph position; resume value is persisted by LangGraph."""
    response = interrupt({
        "type": "closure_confirmation",
        "thread_id": state["thread_id"],
        "items": state.get("pending_confirmation", []),
    })
    return {"human_response": response, "pending_confirmation": []}


def needs_human_confirmation(state: DayendState) -> str:
    closure = state.get("closure_result")
    if closure and closure.data.needs_confirmation_ids:
        return "human_confirmation"
    return "planning"
