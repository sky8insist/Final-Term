from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services import mastery_service, study_plan_service

client = TestClient(app)


def test_study_plan_routes_require_login():
    assert client.get("/api/v1/study-plans/today").status_code == 401
    assert client.get("/api/v1/review/subject/mastery").status_code == 401
    assert client.post("/api/v1/study-plans", json={
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
