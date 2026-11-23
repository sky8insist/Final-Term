from datetime import UTC, datetime, timedelta

from app.services.learner_state_service import derive_state
from app.services.mastery_service import calculate_mastery
from app.services import course_service, mastery_service
from types import SimpleNamespace

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def mastered_row():
    return {"mastery": 0.9, "confidence": 1, "attempts": 6,
            "next_review_at": (NOW + timedelta(days=3)).isoformat(),
            "metadata": {"assessmentCount": 6, "assessmentCorrectStreak": 6}}


def test_reading_and_self_rating_cannot_establish_mastery():
    assert derive_state(None)["state"] == "not_started"
    assert derive_state(None, covered=True)["state"] == "covered"
    row = mastered_row()
    row["metadata"] = {"lastEvidence": {"selfRating": 1}, "assessmentCount": 0}
    assert derive_state(row, now=NOW)["state"] == "practicing"
    plain = calculate_mastery(previous=0.5, attempts=2, correct=False, difficulty="medium")
    high_confidence = calculate_mastery(previous=0.5, attempts=2, correct=False, difficulty="medium", self_rating=1)
    assert plain[:2] == high_confidence[:2]


def test_mastered_requires_assessment_count_streak_and_confidence():
    assert derive_state(mastered_row(), now=NOW)["state"] == "mastered"
    for count, streak, confidence in [(2, 6, 1), (6, 2, 1), (6, 6, 0.2)]:
        row = mastered_row()
        row["metadata"].update(assessmentCount=count, assessmentCorrectStreak=streak)
        row["confidence"] = confidence
        assert derive_state(row, now=NOW)["state"] == "practicing"


def test_due_and_declining_mastery_become_at_risk():
    row = mastered_row()
    row["next_review_at"] = NOW.isoformat()
    assert derive_state(row, now=NOW)["state"] == "at_risk"
    row = mastered_row()
    row["metadata"]["masteredAt"] = (NOW - timedelta(days=7)).isoformat()
    row["mastery"] = 0.5
    assert derive_state(row, now=NOW)["state"] == "at_risk"


def test_high_confidence_wrong_answer_is_misconception_risk():
    row = {"mastery": 0.4, "confidence": 0.5, "attempts": 3,
           "metadata": {"misconceptionRisk": 0.9, "lastEvidence": {"selfRating": 0.9}}}
    state = derive_state(row, now=NOW)
    assert state["state"] == "at_risk"
    assert state["learnerConfidence"] == 0.9
    assert state["masteryConfidence"] == 0.5


def test_performance_history_tracks_coverage_mastery_and_flashcard_source(monkeypatch):
    tables = {"knowledge_mastery": [], "mastery_history": [], "topic_coverage": [{"knowledge_point_id": "topic"}]}
    class Query:
        def __init__(self, name): self.name = name
        def select(self, *args): return self
        def eq(self, *args): return self
        def limit(self, *args): return self
        def upsert(self, payload, **kwargs): tables[self.name] = [payload]; return self
        def insert(self, payload): tables[self.name].append(payload); return self
        def execute(self): return SimpleNamespace(data=tables[self.name])
    db = SimpleNamespace(table=Query)
    monkeypatch.setattr(mastery_service, "get_supabase_client", lambda: db)
    monkeypatch.setattr(course_service, "resolve_topic", lambda **_: {"id": "topic", "knowledge_key": "stable-key"})
    args = {"user_id": "u", "subject_id": "s", "knowledge_key": "alias", "correct": True, "difficulty": "medium"}
    first = mastery_service.record_performance(**args)
    assert first["knowledge_key"] == "stable-key"
    assert tables["mastery_history"][0]["evidence"]["stateBefore"] == "covered"
    assert derive_state(first)["state"] == "practicing"
    for _ in range(6):
        saved = mastery_service.record_performance(**args)
    assert derive_state(saved)["state"] == "mastered"
    assert saved["metadata"]["masteredAt"]
    count = saved["metadata"]["assessmentCount"]
    flashed = mastery_service.record_performance(**args, evidence_type="flashcard")
    assert flashed["metadata"]["assessmentCount"] == count
    tables["knowledge_mastery"][0]["metadata"].update(flashcardRecallRisk=True, assessmentCorrectStreak=0)
    for _ in range(2):
        recovered = mastery_service.record_performance(**args)
        assert recovered["metadata"]["flashcardRecallRisk"]
        assert derive_state(recovered)["state"] == "at_risk"
    recovered = mastery_service.record_performance(**args)
    assert not recovered["metadata"]["flashcardRecallRisk"]
    assert derive_state(recovered)["state"] == "mastered"
    wrong = mastery_service.record_performance(**{**args, "correct": False}, self_rating=0.9)
    assert derive_state(wrong)["state"] == "at_risk"
    assert tables["mastery_history"][-1]["evidence"]["stateAfter"] == "at_risk"
