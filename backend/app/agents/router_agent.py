def route_intent(message: str) -> str:
    lowered = message.lower()
    if "quiz" in lowered or "test" in lowered:
        return "quiz"
    if "outline" in lowered or "summary" in lowered:
        return "outline"
    return "qa"
