import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.exam import ConfirmResponseRequest, ExamGenerateRequest, ResumeQuizRequest
from app.services import exam_service as service


def db_rows(monkeypatch, rows):
    db = MagicMock()
    def table(name):
        query = MagicMock()
        for method in ["select", "eq", "limit", "order"]: getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=rows.get(name, []))
        return query
    db.table.side_effect = table
    monkeypatch.setattr(service, "get_supabase_client", lambda: db)
    return db


def test_mode_defaults_and_explicit_choice():
    values = {"subjectId": "s", "scope": "topic", "questionTypes": [{"questionType": "single_choice", "count": 1, "pointsEach": 2}]}
    assert ExamGenerateRequest(**values).assessment_mode == "formal"
    assert ExamGenerateRequest(**values, assessmentType="practice").assessment_mode == "adaptive"
    assert ExamGenerateRequest(**values, assessmentType="practice", assessmentMode="formal").assessment_mode == "formal"


@pytest.mark.parametrize("values", [{"responseSeconds": -1}, {"responseSeconds": 86401}, {"hintCount": -1}, {"hintCount": 101}])
def test_invalid_metrics_are_rejected(values):
    with pytest.raises(ValidationError): ConfirmResponseRequest(response="A", **values)


def test_resume_requires_review_note():
    with pytest.raises(ValidationError): ResumeQuizRequest(remediationNote="继续")


def test_formal_exam_cannot_confirm_single_question(monkeypatch):
    db_rows(monkeypatch, {"exam_attempts": [{"id": "a", "exam_id": "e", "status": "in_progress"}]})
    monkeypatch.setattr(service, "get_exam", lambda **_: {"assessment_mode": "formal"})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.confirm_response(user_id="u", attempt_id="a", question_id="q", response_value="A"))
    assert caught.value.status_code == 409


def test_formal_unsubmitted_attempt_hides_partial_grades(monkeypatch):
    db_rows(monkeypatch, {"exam_attempts": [{"id": "a", "exam_id": "e", "status": "in_progress"}],
                         "grading_results": [{"question_id": "q", "correct_answer": "secret"}]})
    get_exam = MagicMock(return_value={"assessment_mode": "formal", "questions": []})
    monkeypatch.setattr(service, "get_exam", get_exam)
    assert service.get_attempt(user_id="u", attempt_id="a")["results"] == {}
    assert all(not call.kwargs.get("include_answers", False) for call in get_exam.call_args_list)


def test_formal_answers_cannot_be_exported_before_submit(monkeypatch):
    db_rows(monkeypatch, {})
    monkeypatch.setattr(service, "get_exam", lambda **_: {"assessment_mode": "formal"})
    with pytest.raises(HTTPException) as caught:
        service.export_exam(user_id="u", exam_id="e", export_format="markdown", include_answers=True)
    assert caught.value.status_code == 409


def test_paused_quiz_cannot_save_or_submit(monkeypatch):
    db_rows(monkeypatch, {"exam_attempts": [{"id": "a", "status": "in_progress", "adaptive_state": {"paused": True}}]})
    with pytest.raises(HTTPException) as saved: service.save_response(user_id="u", attempt_id="a", question_id="q", response_value="A")
    with pytest.raises(HTTPException) as submitted: asyncio.run(service.submit_attempt(user_id="u", attempt_id="a"))
    assert saved.value.status_code == submitted.value.status_code == 409


def test_adaptive_cannot_bypass_per_question_confirmation(monkeypatch):
    db_rows(monkeypatch, {"exam_attempts": [{"id": "a", "exam_id": "e", "status": "in_progress"}]})
    monkeypatch.setattr(service, "get_exam", lambda **_: {"assessment_mode": "adaptive", "questions": [{"id": "q"}]})
    with pytest.raises(HTTPException) as caught: asyncio.run(service.submit_attempt(user_id="u", attempt_id="a"))
    assert caught.value.status_code == 409


def test_concurrent_grade_replay_does_not_update_mastery(monkeypatch):
    db = MagicMock(); query = db.table.return_value
    for method in ["upsert", "select", "eq", "limit"]: getattr(query, method).return_value = query
    query.execute.side_effect = [SimpleNamespace(data=[]), SimpleNamespace(data=[{"id": "existing"}])]
    mastery = MagicMock(); monkeypatch.setattr(service, "record_performance", mastery)
    result = service._record_grade(client=db, user_id="u", attempt={"id": "a", "subject_id": "s"}, item={"id": "q"},
        grade={"earnedPoints": 0, "maxPoints": 2, "isCorrect": False, "feedback": "", "earnedCriteria": [], "missingCriteria": [], "errorType": None})
    assert result["id"] == "existing"
    mastery.assert_not_called()
