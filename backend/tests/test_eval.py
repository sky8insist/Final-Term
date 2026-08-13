import json
from pathlib import Path
from typing import get_args

from app.models.assistant import AssistantIntent


def test_intent_evaluation_fixture_is_complete_and_valid():
    fixture = Path(__file__).parents[1] / "evals" / "intent_cases.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    supported = set(get_args(AssistantIntent))

    assert len(cases) >= 16
    assert all(case.get("input", "").strip() for case in cases)
    assert all(case.get("expected") in supported for case in cases)
