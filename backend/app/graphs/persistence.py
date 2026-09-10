from app.persistence.store import persist_validated_state
from app.state.dayend_state import DayendState


def persistence_node(state: DayendState) -> dict:
    persist_validated_state(state)
    return {"final_output": {"status": "completed"}}
