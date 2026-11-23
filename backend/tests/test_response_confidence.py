from types import SimpleNamespace
from unittest.mock import MagicMock
import asyncio
from fastapi import HTTPException

import pytest
from pydantic import ValidationError

from app.models.exam import ConfirmResponseRequest, SaveResponseRequest
from app.services import exam_service
from app.services.study_signal_service import calculate_need_score


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_confidence_rejected(confidence):
    with pytest.raises(ValidationError):
        ConfirmResponseRequest(response="A", learnerConfidence=confidence)


def test_confidence_is_optional_and_zero_is_preserved():
    assert ConfirmResponseRequest(response="A").learner_confidence is None
    assert SaveResponseRequest(questionId="q", response="A", learnerConfidence=0).learner_confidence == 0


def test_grade_persists_confidence_and_updates_mastery(monkeypatch):
    db = MagicMock()
    query = db.table.return_value
    query.upsert.return_value = query
    query.select.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": "g"}])
    mastery_calls = []
    monkeypatch.setattr(exam_service, "record_performance", lambda **values: mastery_calls.append(values))
    exam_service._record_grade(client=db, user_id="u", attempt={"id": "a", "subject_id": "s"},
        item={"id": "q", "knowledge_key": "topic", "difficulty": "medium"},
        grade={"earnedPoints": 0, "maxPoints": 2, "isCorrect": False, "feedback": "复习",
               "earnedCriteria": [], "missingCriteria": [], "errorType": "concept"}, learner_confidence=0.9)
    stored = query.upsert.call_args.args[0]
    assert stored["learner_confidence"] == stored["confidence_mismatch"] == 0.9
    assert mastery_calls[0]["self_rating"] == 0.9
    assert mastery_calls[0]["correct"] is False


def test_confidence_mismatch_changes_recommendation_priority():
    ordinary, _ = calculate_need_score({"mastery": 0.5, "confidenceMismatch": 0})
    mismatch, _ = calculate_need_score({"mastery": 0.5, "confidenceMismatch": 0.9})
    assert mismatch > ordinary


def test_confirm_replay_is_idempotent_and_cannot_change_confidence(monkeypatch):
    grade = {"earned_points": 0, "max_points": 2, "is_correct": False,
             "learner_confidence": 0.9, "confidence_mismatch": 0.9}
    rows = {"exam_attempts": [{"id": "a", "exam_id": "e", "status": "in_progress"}],
            "grading_results": [grade], "exam_responses": [{"response": "A"}]}
    db = MagicMock()
    def table(name):
        query = MagicMock()
        for method in ["select", "eq", "limit"]:
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=rows[name])
        return query
    db.table.side_effect = table
    monkeypatch.setattr(exam_service, "get_supabase_client", lambda: db)
    monkeypatch.setattr(exam_service, "get_exam", lambda **_: {"questions": [
        {"id": "q", "correctAnswer": "B", "explanation": "固定答案"}]})
    record = MagicMock()
    monkeypatch.setattr(exam_service, "record_performance", record)
    args = {"user_id": "u", "attempt_id": "a", "question_id": "q", "response_value": "A"}
    result = asyncio.run(exam_service.confirm_response(**args, learner_confidence=0.9))
    assert result["learnerConfidence"] == 0.9
    with pytest.raises(HTTPException) as caught:
        asyncio.run(exam_service.confirm_response(**args, learner_confidence=0.25))
    assert caught.value.status_code == 409
    record.assert_not_called()
