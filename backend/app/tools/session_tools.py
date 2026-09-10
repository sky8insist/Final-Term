from langchain_core.tools import tool


@tool
def get_current_session_state(thread_id: str, summary: str | None = None) -> dict:
    """Return the supplied, read-only summary for the current Dayend session."""
    return {"thread_id": thread_id, "summary": summary or ""}


@tool
def get_last_closure_status(thread_id: str) -> dict:
    """Return an empty status until the persistence layer is introduced."""
    return {"thread_id": thread_id, "status": "not_available"}
