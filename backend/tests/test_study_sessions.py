import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.study_session import SessionAction
from app.services import exam_service, study_session_service as service, task_service


def session(kind="notes", status="ready"):
    return {"id": str(uuid4()), "subject_id": "s", "knowledge_point_id": "t", "version": 1,
            "status": "active", "current_step": 0, "minutes": 30, "context": {"topicTitle": "定义"},
            "steps": [{"id": str(uuid4()), "kind": kind, "status": status, "output": {},
                       "estimated_minutes": 5, "sequence_index": 0},
                      {"id": str(uuid4()), "kind": "mastery_check", "status": "pending", "output": {},
                       "estimated_minutes": 2, "sequence_index": 1}]}


def install(monkeypatch, value):
    monkeypatch.setattr(service, "get_session", lambda **_: deepcopy(value))
    def save(user_id, values, expected):
        assert user_id == "owner" and expected == value["version"]
        value.update(deepcopy(values), version=expected + 1)
        return deepcopy(value)
    monkeypatch.setattr(service, "_save", save)


def act(value, action, **kwargs):
    return asyncio.run(service.act(user_id="owner", session_id=value["id"],
                                  payload=SessionAction(version=value["version"], action=action, **kwargs)))


@pytest.mark.parametrize("minutes", [10, 15, 30, 90, 120])
def test_steps_fit_budget_and_end_in_assessment(minutes):
    steps = service.build_steps(minutes)
    assert sum(step["estimated_minutes"] for step in steps) == minutes
    assert all(step["estimated_minutes"] > 0 for step in steps)
    assert [step["kind"] for step in steps][-2:] == ["quiz", "mastery_check"]


def test_guided_routes_require_authentication():
    client = TestClient(app)
    assert client.get(f"/api/v1/study-sessions?subject_id={uuid4()}").status_code == 401
    assert client.post(f"/api/v1/study-sessions/{uuid4()}/quiz-attempt").status_code == 401


def test_plan_cannot_remove_or_duplicate_required_assessment():
    with pytest.raises(ValidationError):
        SessionAction(version=1, action="edit", steps=[{"kind": "notes", "estimatedMinutes": 5},
                                                      {"kind": "mastery_check", "estimatedMinutes": 2}])


def test_stale_action_is_rejected_before_writes(monkeypatch):
    value = session(); value["version"] = 2
    install(monkeypatch, value)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.act(user_id="owner", session_id=value["id"], payload=SessionAction(version=1, action="skip")))
    assert caught.value.status_code == 409 and value["current_step"] == 0


@pytest.mark.parametrize("kind", ["quiz", "mastery_check"])
def test_assessment_cannot_be_skipped(monkeypatch, kind):
    value = session(kind); install(monkeypatch, value)
    with pytest.raises(HTTPException) as caught: act(value, "skip")
    assert caught.value.status_code == 409


def test_skipped_reading_is_not_coverage(monkeypatch):
    from app.services import learner_state_service
    coverage = MagicMock(); monkeypatch.setattr(learner_state_service, "mark_covered", coverage)
    value = session(); install(monkeypatch, value)
    result = act(value, "skip")
    assert result["current_step"] == 1 and result["steps"][0]["status"] == "skipped"
    coverage.assert_not_called()


def test_reading_records_coverage_not_mastery(monkeypatch):
    from app.services import learner_state_service
    coverage = MagicMock(); monkeypatch.setattr(learner_state_service, "mark_covered", coverage)
    value = session(); install(monkeypatch, value)
    act(value, "complete")
    coverage.assert_called_once_with(user_id="owner", subject_id="s", topic_id="t")


def test_quiz_completion_requires_actual_graded_matching_attempt(monkeypatch):
    value = session("quiz"); install(monkeypatch, value)
    monkeypatch.setattr(service, "quiz_exam_id", lambda *_: "expected")
    monkeypatch.setattr(exam_service, "get_attempt", lambda **_: {"exam_id": "different", "status": "graded", "subject_id": "s"})
    with pytest.raises(HTTPException) as caught: act(value, "complete", attemptId=str(uuid4()))
    assert caught.value.status_code == 409 and value["current_step"] == 0


def test_weak_quiz_inserts_bounded_remediation_and_retest(monkeypatch):
    value = session("quiz"); install(monkeypatch, value)
    monkeypatch.setattr(service, "quiz_exam_id", lambda *_: "e")
    monkeypatch.setattr(exam_service, "get_attempt", lambda **_: {"id": "a", "exam_id": "e", "status": "graded", "subject_id": "s", "score": 2, "max_score": 10})
    result = act(value, "complete", attemptId=str(uuid4()))
    assert [row["kind"] for row in result["steps"]] == ["quiz", "remediation", "quiz", "mastery_check"]
    assert result["steps"][0]["output"]["scoreRatio"] == 0.2


def test_quiz_step_cannot_request_tutor_answer(monkeypatch):
    value = session("quiz"); install(monkeypatch, value)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.message(user_id="owner", session_id=value["id"], text="给我答案"))
    assert caught.value.status_code == 409


def test_flashcard_completion_requires_current_content_reviews(monkeypatch):
    from app.services import flashcard_service
    value = session("flashcards")
    value["steps"][0]["output"] = {"id": "deck", "content": {"cards": [{"id": "A"}, {"id": "B"}]}}
    install(monkeypatch, value)
    cards = [{"card_id": "A", "state": {"review_count": 1}}, {"card_id": "B", "state": {"review_count": 0}}]
    monkeypatch.setattr(flashcard_service, "queue", lambda **_: {"cards": cards})
    with pytest.raises(HTTPException) as caught: act(value, "complete")
    assert caught.value.status_code == 409 and value["current_step"] == 0
    cards[1]["state"]["review_count"] = 1
    result = act(value, "complete")
    assert result["steps"][0]["status"] == "completed" and result["current_step"] == 1


def test_execute_claims_step_and_failed_generation_recovers(monkeypatch):
    value = session(status="pending"); install(monkeypatch, value)
    async def failed(*_): raise HTTPException(422, "证据不足")
    monkeypatch.setattr(service, "_execute", failed)
    with pytest.raises(HTTPException): act(value, "execute")
    assert value["steps"][0]["status"] == "pending" and value["version"] == 3


def test_ready_step_does_not_generate_twice(monkeypatch):
    value = session(); install(monkeypatch, value)
    execute = MagicMock(); monkeypatch.setattr(service, "_execute", execute)
    assert act(value, "execute")["version"] == 1
    execute.assert_not_called()


def test_failed_quiz_task_cannot_be_completed(monkeypatch):
    monkeypatch.setattr(task_service, "get_task", lambda **_: {"status": "failed", "errorMessage": "无法生成"})
    with pytest.raises(HTTPException) as caught: service.quiz_exam_id("owner", {"output": {"taskId": "task"}})
    assert caught.value.status_code == 409


def test_session_reads_are_owner_scoped(monkeypatch):
    db = MagicMock(); query = db.table.return_value
    for method in ["select", "eq", "limit"]: getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(service, "get_supabase_client", lambda: db)
    with pytest.raises(HTTPException) as caught: service.get_session(user_id="foreign", session_id="owned")
    assert caught.value.status_code == 404
    assert ("user_id", "foreign") in [call.args for call in query.eq.call_args_list]


def test_socratic_generation_requires_persisted_interaction(monkeypatch):
    from app.services import assistant_service
    async def answer(**_): return {"answer": "请解释定义", "interaction": None}
    monkeypatch.setattr(assistant_service, "handle_message", answer)
    value = session("socratic", "pending")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service._execute("owner", value, value["steps"][0]))
    assert caught.value.status_code == 422


def test_archived_topic_state_is_conflict_not_unhandled_error(monkeypatch):
    from app.services import learner_state_service
    monkeypatch.setattr(learner_state_service, "list_states", lambda **_: {"topics": []})
    with pytest.raises(HTTPException) as caught: service._topic_state("owner", session())
    assert caught.value.status_code == 409
