from langchain_core.tools import tool
from app.persistence.store import get_night_state


@tool
def get_last_night_plan(thread_id: str) -> dict:
    """Read the persisted prior-night plan for this Dayend thread."""
    night = get_night_state(thread_id) or {}
    return {"thread_id": thread_id, "plan": night.get("planning")}


@tool
def get_confirmed_items(thread_id: str) -> dict:
    """Read confirmed closure data for this Dayend thread."""
    night = get_night_state(thread_id) or {}
    return {"thread_id": thread_id, "items": night.get("confirmation")}
