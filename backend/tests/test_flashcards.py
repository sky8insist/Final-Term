from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.artifacts import FlashcardReview
from app.services import course_service, flashcard_service as service
from app.services.learner_state_service import derive_state

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def test_again_is_earlier_than_easy_and_cards_have_independent_intervals():
    state = {"stability": 4, "difficulty": 5, "last_review": (NOW - timedelta(days=4)).isoformat()}
    outcomes = {rating: service.schedule(state, rating, now=NOW) for rating in service.RATINGS}
    assert outcomes["again"]["nextReview"] < outcomes["hard"]["nextReview"] < outcomes["good"]["nextReview"] < outcomes["easy"]["nextReview"]
    assert state["stability"] == 4
    assert outcomes["again"]["difficulty"] > outcomes["easy"]["difficulty"]
    assert outcomes["again"]["retrievabilityBefore"] == 0.9
    later = service.schedule({**state, "last_review": (NOW - timedelta(days=8)).isoformat()}, "good", now=NOW)
    assert later["retrievabilityBefore"] < 0.9


@pytest.mark.parametrize("rating", sorted(service.RATINGS))
def test_schedule_bounds_and_new_cards(rating):
    result = service.schedule({}, rating, now=NOW)
    assert result["nextReview"] > NOW.isoformat()
    assert 1 <= result["difficulty"] <= 10 and 0.25 <= result["stability"] <= 365
    maximum = service.schedule({"stability": 365, "difficulty": 10, "last_review": NOW.isoformat()}, rating, now=NOW)
    assert datetime.fromisoformat(maximum["nextReview"]) <= NOW + timedelta(days=365)


@pytest.mark.parametrize("values", [{"rating": "invalid"}, {"version": -1}, {"requestId": "invalid"}, {"responseSeconds": -1}, {"responseSeconds": float("inf")}])
def test_invalid_review_input_is_rejected(values):
    with pytest.raises(ValidationError): FlashcardReview.model_validate({"cardId": "card", "rating": "easy", **values})


def test_recall_failure_cannot_be_cleared_by_flashcard_self_rating():
    row = {"attempts": 10, "mastery": 0.99, "confidence": 1,
           "metadata": {"masteredAt": NOW.isoformat(), "assessmentCount": 10,
                        "assessmentCorrectStreak": 10, "flashcardRecallRisk": True},
           "next_review_at": (NOW + timedelta(days=30)).isoformat()}
    assert derive_state(row, now=NOW)["state"] == "at_risk"


def install(monkeypatch, *, replay=None, version=1, archived=False, rpc_error=None):
    card = {"artifact_id": "a", "card_id": "c", "subject_id": "s", "knowledge_point_id": "t", "front": "Topic"}
    state = {"version": version, "difficulty": 5, "stability": 1, "last_review": None}
    current = {"mastery": 0.95, "confidence": 0.7, "attempts": 10, "correct_attempts": 9,
        "updated_at": NOW.isoformat(), "metadata": {"masteredAt": NOW.isoformat(), "assessmentCount": 8, "assessmentCorrectStreak": 3}}
    tables = {"flashcard_review_logs": [replay] if replay else [], "flashcards": [card],
              "flashcard_review_state": [state], "knowledge_mastery": [current]}
    calls = []
    class Query:
        def __init__(self, name): self.name = name
        def select(self, *args): return self
        def eq(self, *args): calls.append((self.name, args)); return self
        def limit(self, *args): return self
        def execute(self): return SimpleNamespace(data=tables[self.name])
    def rpc(name, values):
        calls.append((name, values))
        def execute():
            if rpc_error: raise rpc_error
            return SimpleNamespace(data=values)
        return SimpleNamespace(execute=execute)
    monkeypatch.setattr(service, "get_supabase_client", lambda: SimpleNamespace(table=Query, rpc=rpc))
    monkeypatch.setattr(course_service, "_owned", lambda **_: {"id": "t", "knowledge_key": "stable", "archived": archived})
    return calls


def test_review_preserves_objective_evidence_and_records_recall_risk(monkeypatch):
    calls = install(monkeypatch)
    result = service.review(user_id="u", artifact_id="a", card_id="c", rating="again", request_id=str(uuid4()), version=1)
    m = result["p_values"]["mastery"]
    assert m["confidence"] == 0.7 and m["metadata"]["assessmentCount"] == 8
    assert m["metadata"]["flashcardRecallRisk"] and m["metadata"]["assessmentCorrectStreak"] == 0
    assert result["p_values"]["evidence"]["evidenceType"] == "flashcard"
    assert result["p_values"]["evidence"]["stateAfter"] == "at_risk"
    assert all((name, ("user_id", "u")) in calls for name in ["flashcards", "flashcard_review_state", "knowledge_mastery"])


def test_receipt_replay_never_recomputes_mastery(monkeypatch):
    request_id = str(uuid4())
    calls = install(monkeypatch, replay={"artifact_id": "a", "card_id": "c", "rating": "easy", "expected_version": 1, "result": {"reviewId": request_id}})
    assert service.review(user_id="u", artifact_id="a", card_id="c", rating="easy", request_id=request_id, version=1) == {"reviewId": request_id}
    assert not any(name == "commit_flashcard_review" for name, _ in calls)
    with pytest.raises(HTTPException) as caught:
        service.review(user_id="u", artifact_id="a", card_id="c", rating="again", request_id=request_id, version=1)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("values", [{"version": 2}, {"archived": True}])
def test_conflicts_do_not_commit(monkeypatch, values):
    calls = install(monkeypatch, **values)
    with pytest.raises(HTTPException) as caught: service.review(user_id="u", artifact_id="a", card_id="c", rating="good", version=1)
    assert caught.value.status_code == 409
    assert not any(name == "commit_flashcard_review" for name, _ in calls)
