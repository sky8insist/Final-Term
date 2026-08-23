import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents import router_agent
from app.main import app
from app.models.assistant import AssistantMessageRequest, IntentDecision
from app.services import assistant_service
from app.services.llm_service import LLMServiceError
from app.services.role_service import recommend_role

client = TestClient(app)


def test_assistant_requires_login():
    response = client.post("/api/v1/assistant/messages", json={
        "subjectId": str(uuid4()), "message": "解释矩阵", "sessionId": str(uuid4()),
    })
    assert response.status_code == 401


def test_router_falls_back_to_chinese_intent_rules(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise LLMServiceError("offline")
    monkeypatch.setattr(router_agent, "generate_json_async", fail)

    decision = asyncio.run(router_agent.route_intent("请根据资料生成一份模拟试卷"))
    assert decision.primary_intent == "generate_exam"
    assert decision.confidence >= 0.55


def test_role_recommendation_uses_learning_level():
    key, config = recommend_role(requested="auto", profile={"level": "beginner"}, intent="qa")
    assert key == "beginner"
    assert config["name"] == "小白详细模式"


@pytest.mark.parametrize(("message", "expected"), [
    ("请用小白方式解释特征值", "explain_concept"),
    ("根据第三章生成思维导图", "generate_mind_map"),
    ("针对这份资料出五道专项练习", "generate_practice"),
    ("生成一套期末模拟试卷", "generate_exam"),
    ("分析这张表格的第三列", "analyze_table"),
    ("查看我的知识点掌握进度", "show_progress"),
    ("联网补充这个概念", "external_research"),
])
def test_fallback_router_covers_required_learning_scenarios(message, expected):
    assert router_agent._fallback(message).primary_intent == expected


def test_socratic_role_forbids_immediate_final_answer():
    key, config = recommend_role(requested="socratic", profile={}, intent="qa")
    assert key == "socratic"
    assert "不要立即给出最终答案" in config["instruction"]


def test_low_confidence_intent_returns_clarification(monkeypatch):
    async def uncertain(_message):
        return IntentDecision(
            primary_intent="qa", confidence=0.3, needs_retrieval=True,
            needs_clarification=True, clarification_question="请说明复习范围",
            required_skills=[],
        )
    monkeypatch.setattr(assistant_service, "route_intent", uncertain)
    monkeypatch.setattr(assistant_service.hermes_memory_service, "get_profile", lambda **_: {"level": "beginner"})
    monkeypatch.setattr(assistant_service.memory_service, "record_qa_history", lambda **_: {"id": "msg-1"})
    payload = AssistantMessageRequest(
        subjectId=str(uuid4()), message="帮我一下", sessionId=str(uuid4()), role="auto",
    )
    result = asyncio.run(assistant_service.handle_message(user_id=str(uuid4()), payload=payload))

    assert result["needsClarification"] is True
    assert result["answer"] == "请说明复习范围"
    assert result["citations"] == []


def test_assistant_forwards_session_role_generation_and_queues_memory(monkeypatch):
    session_id = str(uuid4())
    subject_id = str(uuid4())
    queued = []

    async def route(_message):
        return IntentDecision(
            primary_intent="qa", confidence=0.9, needs_retrieval=True,
            needs_clarification=False, required_skills=[],
        )

    async def answer(**kwargs):
        assert kwargs["session_id"] == session_id
        assert "少用术语" in kwargs["teaching_instruction"]
        return {
            "answer": "基于资料的回答",
            "citations": [{"id": "citation-1"}],
            "messageId": "msg-1",
            "generation": {"model": "test-model", "mocked": False},
        }

    monkeypatch.setattr(assistant_service, "route_intent", route)
    monkeypatch.setattr(assistant_service.hermes_memory_service, "get_profile", lambda **_: {"memoryEnabled": True})
    monkeypatch.setattr(assistant_service.hermes_memory_service, "list_active_skills", lambda **_: [])
    monkeypatch.setattr(assistant_service.rag_service, "answer_with_rag", answer)
    from app.worker.tasks import review_learning_interaction
    monkeypatch.setattr(review_learning_interaction, "delay", lambda *args: queued.append(args))

    payload = AssistantMessageRequest(
        subjectId=subject_id, message="解释这个概念", sessionId=session_id, role="beginner",
    )
    result = asyncio.run(assistant_service.handle_message(user_id=str(uuid4()), payload=payload))

    assert result["role"]["id"] == "beginner"
    assert result["generation"]["model"] == "test-model"
    assert result["memoryUpdates"] == [{"status": "queued", "type": "background_review"}]
    assert queued[0][2] == session_id
