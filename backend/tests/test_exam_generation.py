import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.main import app
from app.models.exam import ExamGenerateRequest
from app.models.user import CurrentUser
from app.services import exam_generation_service, exam_service
from app.services.llm_service import LLMServiceError


client = TestClient(app)


def _user():
    return CurrentUser(id="00000000-0000-0000-0000-000000000001", email="student@example.com")


def _payload():
    return {
        "subjectId": "00000000-0000-0000-0000-000000000002",
        "title": "专项练习", "durationMinutes": 20, "difficulty": "medium",
        "assessmentType": "practice", "avoidSeen": False,
        "scope": "战略的作用", "knowledgePolicy": "course_first",
        "questionTypes": [
            {"questionType": "single_choice", "count": 2, "pointsEach": 2},
            {"questionType": "true_false", "count": 1, "pointsEach": 1},
            {"questionType": "fill_blank", "count": 1, "pointsEach": 2},
        ],
    }


def test_generation_request_round_trips_through_task_metadata():
    request = ExamGenerateRequest(**_payload())
    stored = request.model_dump(by_alias=True)

    assert "subjectId" in stored and "subject_id" not in stored
    assert "questionTypes" in stored and "question_types" not in stored
    assert "questionType" in stored["questionTypes"][0]
    assert ExamGenerateRequest(**stored) == request


def test_practice_requires_topic_but_mock_exam_does_not():
    practice = _payload()
    practice["scope"] = "   "
    with pytest.raises(ValidationError, match="Practice topic is required"):
        ExamGenerateRequest(**practice)

    practice.pop("scope")
    practice["assessmentType"] = "mock"
    practice.pop("knowledgePolicy")
    request = ExamGenerateRequest(**practice)
    assert request.scope is None
    assert request.knowledge_policy == "course_only"


def test_question_types_allow_zero_but_total_must_be_positive():
    payload = _payload()
    payload["questionTypes"] = [
        {"questionType": "single_choice", "count": 10, "pointsEach": 2},
        {"questionType": "true_false", "count": 0, "pointsEach": 1},
        {"questionType": "fill_blank", "count": 0, "pointsEach": 2},
    ]
    assert ExamGenerateRequest(**payload).question_types[1].count == 0

    for item in payload["questionTypes"]:
        item["count"] = 0
    with pytest.raises(ValidationError, match="at least one question"):
        ExamGenerateRequest(**payload)


def test_generation_endpoint_queues_persistent_task(monkeypatch):
    app.dependency_overrides[get_current_user] = _user
    monkeypatch.setattr(exam_generation_service, "create_generation_task", lambda **_: {
        "id": "task-1", "subjectId": _payload()["subjectId"], "materialId": None,
        "taskType": "exam_generation", "status": "queued", "stage": "queued",
        "progress": 0, "attempts": 0, "maxAttempts": 1, "metadata": {},
    })
    dispatched = []
    from app.worker import tasks
    monkeypatch.setattr(tasks.generate_exam, "delay", dispatched.append)
    response = client.post("/api/v1/exams/generations", json=_payload())
    app.dependency_overrides.clear()
    assert response.status_code == 202
    assert response.json()["taskType"] == "exam_generation"
    assert dispatched == ["task-1"]


def test_fill_blank_and_objective_types_validate_without_rubric():
    specs = [
        {"questionType": "single_choice", "count": 1, "pointsEach": 2},
        {"questionType": "true_false", "count": 1, "pointsEach": 1},
        {"questionType": "fill_blank", "count": 1, "pointsEach": 2},
    ]
    questions = [
        {"questionType": "single_choice", "stem": "战略关注什么？", "options": ["长期方向", "每日排班"], "correctAnswer": "长期方向", "explanation": "战略关注长期方向", "citationIds": ["c1"]},
        {"questionType": "true_false", "stem": "战术等同于长期方向", "options": [], "correctAnswer": False, "explanation": "战术偏向具体行动", "citationIds": ["c1"]},
        {"questionType": "fill_blank", "stem": "战略决定组织的____。", "options": [], "correctAnswer": "长期方向", "explanation": "资料强调长期方向", "citationIds": ["c1"]},
    ]
    assert len(exam_service._validate_generated_questions(
        {"questions": questions}, specs, {"c1"},
    )) == 3


def test_transport_timeout_retries_only_the_failed_batch(monkeypatch):
    async def evidence(**_kwargs):
        return {
            "citations": [{"id": "c1", "filename": "notes.pdf", "chunkText": "战略决定长期方向", "sourceType": "material"}],
            "retrieval": {"externalUsed": False, "warnings": []},
        }
    monkeypatch.setattr(exam_service, "retrieve_exam_evidence", evidence)
    calls = []

    async def timeout(*_args, **_kwargs):
        calls.append(1)
        raise LLMServiceError("LLM API request timed out")

    monkeypatch.setattr(exam_service, "generate_json_async", timeout)
    payload = ExamGenerateRequest(**_payload())
    with pytest.raises(HTTPException) as caught:
        asyncio.run(exam_service.generate_exam(user_id="user", payload=payload))
    assert caught.value.status_code == 504
    assert len(calls) == 2


def test_worker_persists_progress_and_exam_id(monkeypatch):
    from app.worker import tasks as worker_tasks
    from app.services import observability_service

    row = {
        "id": "task-1", "user_id": "user", "subject_id": _payload()["subjectId"],
        "status": "queued", "attempts": 0,
        "metadata": {"request": _payload(), "currentStage": "queued", "examId": None},
    }

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self
        def execute(self): return type("Response", (), {"data": [row]})()

    class Db:
        def table(self, name):
            assert name == "processing_tasks"
            return Query()

    updates = []
    monkeypatch.setattr(worker_tasks, "get_supabase_client", lambda: Db())
    monkeypatch.setattr(worker_tasks.task_service, "update_task", lambda **values: updates.append(values) or values)
    monkeypatch.setattr(worker_tasks.task_service, "get_task", lambda **_: {"status": "running"})
    monkeypatch.setattr(observability_service, "record_operation", lambda **_: None)

    async def generated(*, on_stage, **_kwargs):
        for stage in ("retrieving", "generating", "validating", "saving"):
            on_stage(stage)
        return {"id": "exam-1"}

    monkeypatch.setattr(exam_service, "generate_exam", generated)
    result = worker_tasks.generate_exam.run("task-1")
    assert result["examId"] == "exam-1"
    assert updates[-1]["status"] == "succeeded"
    assert updates[-1]["metadata"]["examId"] == "exam-1"
