import re


_URGENT_PATTERNS = (r"自杀", r"自傷|自伤", r"不想活", r"kill myself", r"suicide")


def detect_urgent_signal(user_input: str) -> dict:
    """Minimal deterministic escalation detector; semantic risk remains the LLM's job."""
    matches = [pattern for pattern in _URGENT_PATTERNS if re.search(pattern, user_input, re.I)]
    return {"urgent_signal": bool(matches), "matched_patterns": matches}
