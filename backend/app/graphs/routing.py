from app.state.dayend_state import DayendState


def route_supervisor_result(state: DayendState) -> str:
    result = state.get("supervisor_result")
    if result is None:
        return "human_review"
    intent = result.data.primary_intent
    return {
        "day_closure": "closure",
        "emotion_release": "emotion",
        "mixed": "mixed",
        "morning_review": "morning",
    }.get(intent, "human_review")
