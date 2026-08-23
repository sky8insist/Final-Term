from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import mastery_service, study_plan_service
from app.services.study_signal_service import calculate_need_score

client = TestClient(app)


def test_study_plan_routes_require_login():
    assert client.get("/api/v1/study-plans/today").status_code == 401
    assert client.get("/api/v1/review/subject/mastery").status_code == 401
    assert client.post("/api/v1/study-plans", json={
        "subjectId": "subject", "examDate": (date.today() + timedelta(days=7)).isoformat(),
    }).status_code == 401
    assert client.post("/api/v1/study-plans/preview", json={
        "subjectId": "subject", "examDate": (date.today() + timedelta(days=7)).isoformat(),
    }).status_code == 401
    assert client.post("/api/v1/study-plans/generations", json={
        "subjectId": "subject", "examDate": (date.today() + timedelta(days=7)).isoformat(),
    }).status_code == 401


def test_one_failure_does_not_collapse_new_user_mastery():
    mastery, confidence, evidence = mastery_service.calculate_mastery(
        previous=0.5, attempts=0, correct=False, difficulty="medium",
    )
    assert 0.3 < mastery < 0.5
    assert 0 < confidence < 0.5
    assert evidence["performance"] == 0


def test_correct_hard_answer_improves_mastery_more_than_hinted_answer():
    clean, _, _ = mastery_service.calculate_mastery(
        previous=0.5, attempts=3, correct=True, difficulty="hard", hints=0,
    )
    hinted, _, _ = mastery_service.calculate_mastery(
        previous=0.5, attempts=3, correct=True, difficulty="hard", hints=3,
    )
    assert clean > hinted > 0.5


def test_plan_priority_favors_low_mastery():
    weak = study_plan_service._priority({"mastery": 0.2, "confidence": 0.5, "metadata": {}}, 7)
    strong = study_plan_service._priority({"mastery": 0.9, "confidence": 0.5, "metadata": {}}, 7)
    assert weak > strong


def _signal(key: str, need: float) -> dict:
    return {
        "knowledgeKey": key, "title": key, "needScore": need,
        "mastery": 0.4, "confidence": 0.6, "accuracy": 0.5,
        "attemptCount": 4, "sourceSignals": ["practice"],
        "reasons": ["近期练习正确率 50%"], "needComponents": {"forgetting": 0.5},
    }


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
def test_deterministic_schedule_respects_date_and_capacity(days):
    start = date(2026, 8, 23)
    target = start + timedelta(days=days)
    result = study_plan_service.build_schedule(
        signals=[_signal("战略定义", 0.9), _signal("层级关系", 0.7), _signal("执行控制", 0.6)],
        start=start, target=target, daily_minutes=45, reserve_final_day=True,
    )
    usage = {}
    for task in result["tasks"]:
        scheduled = date.fromisoformat(task["scheduled_date"])
        assert start <= scheduled <= target
        usage[scheduled] = usage.get(scheduled, 0) + task["estimated_minutes"]
    assert usage
    assert max(usage.values()) <= 45
    assert result["tasks"][-1]["scheduled_date"] == target.isoformat()


def test_need_score_explains_all_weighted_components():
    score, components = calculate_need_score({
        "mastery": 0.3, "confidence": 0.7, "attemptCount": 5,
        "correctCount": 2, "scoreRatio": 0.4, "dialogueEventCount": 2,
        "hintRequestCount": 1, "importance": 0.8,
    }, now=datetime(2026, 8, 23, tzinfo=timezone.utc))
    assert 0 < score <= 1
    assert set(components) == {"masteryGap", "practiceLoss", "forgetting", "dialogueConfusion", "importance", "dataConfidence"}
