import asyncio
from uuid import uuid4

from app.models.assistant import AssistantMessageRequest, IntentDecision
from app.services import assistant_service
from app.services.dialogue_act_service import classify_by_rules
from app.services.question_context_service import explain_question


def _interaction() -> dict:
    return {
        "id": str(uuid4()), "status": "awaiting_answer", "source_mode": "socratic",
        "question_text": "为什么 P 一定可逆？", "knowledge_key": "矩阵可对角化",
        "attempt_count": 0, "current_step": 0,
        "evidence": {"citations": [{"id": "c1", "sourceName": "讲义", "text": "P的列向量线性无关。"}]},
        "metadata": {},
    }


def test_rules_distinguish_answer_followup_and_new_question():
    active = _interaction()
    context = {"activeInteraction": active, "hasPendingQuestion": True}
    assert classify_by_rules("因为P的列向量线性无关", context).dialogue_act == "answer_to_pending_question"
    assert classify_by_rules("那为什么线性无关就能说明可逆？", context).dialogue_act == "followup_question_same_topic"
    assert classify_by_rules("换个问题，什么是奇异值？", context).dialogue_act == "new_question"
    assert classify_by_rules("我不会，给点提示", context).dialogue_act == "request_hint"


def test_answer_to_socratic_question_uses_evaluator_without_rag(monkeypatch):
    active = _interaction()
    context = {"activeInteraction": active, "hasPendingQuestion": True, "recentTurns": []}
    monkeypatch.setattr(assistant_service, "resolve_conversation_context", lambda **_: context)
    monkeypatch.setattr(assistant_service.hermes_memory_service, "get_profile", lambda **_: {"memoryEnabled": False})
    async def evaluate(**_kwargs):
        return {
            "evaluation": "partially_correct", "confidence": 0.9,
            "matchedConcepts": ["线性无关"], "missingConcepts": ["满秩"],
            "misconceptions": [], "feedback": "这一步正确。", "nextAction": "ask_followup",
            "nextQuestion": "它为什么说明P满秩？", "answer": "这一步正确。\n\n它为什么说明P满秩？",
        }
    monkeypatch.setattr(assistant_service, "evaluate_student_answer", evaluate)
    monkeypatch.setattr(assistant_service, "update_interaction", lambda **_: {**active, "status": "awaiting_answer"})
    monkeypatch.setattr(assistant_service.memory_service, "record_qa_history", lambda **_: {"id": "m1"})
    async def forbidden_rag(**_kwargs):
        raise AssertionError("student answer must not be sent to RAG")
    monkeypatch.setattr(assistant_service.rag_service, "answer_with_rag", forbidden_rag)

    result = asyncio.run(assistant_service.handle_message(
        user_id=str(uuid4()),
        payload=AssistantMessageRequest(
            subjectId=str(uuid4()), sessionId=str(uuid4()), role="socratic",
            message="因为P的列向量线性无关",
        ),
    ))
    assert result["dialogue"]["dialogueAct"] == "answer_to_pending_question"
    assert result["evaluation"]["evaluation"] == "partially_correct"
    assert result["interaction"]["expectsReply"] is True


def test_same_topic_followup_retrieves_contextualized_question(monkeypatch):
    active = _interaction()
    context = {"activeInteraction": active, "hasPendingQuestion": True, "recentTurns": []}
    monkeypatch.setattr(assistant_service, "resolve_conversation_context", lambda **_: context)
    monkeypatch.setattr(assistant_service.hermes_memory_service, "get_profile", lambda **_: {"memoryEnabled": False})
    async def route(_message):
        return IntentDecision(primary_intent="qa", confidence=0.9, needs_retrieval=True,
                              needs_clarification=False, required_skills=[])
    monkeypatch.setattr(assistant_service, "route_intent", route)
    captured = {}
    async def answer(**kwargs):
        captured.update(kwargs)
        return {"answer": "解释", "citations": [], "messageId": "m1", "generation": {}}
    monkeypatch.setattr(assistant_service.rag_service, "answer_with_rag", answer)

    result = asyncio.run(assistant_service.handle_message(
        user_id=str(uuid4()),
        payload=AssistantMessageRequest(
            subjectId=str(uuid4()), sessionId=str(uuid4()), role="beginner",
            message="那为什么线性无关就能说明可逆？",
        ),
    ))
    assert "上一问题：为什么 P 一定可逆？" in captured["question"]
    assert captured["history_question"] == "那为什么线性无关就能说明可逆？"
    assert result["dialogue"]["dialogueAct"] == "followup_question_same_topic"


def test_in_progress_exam_question_does_not_reveal_hidden_answer(monkeypatch):
    interaction = _interaction()
    interaction["metadata"] = {
        "questionContext": True, "answersVisible": False,
        "evaluation": {"correctAnswer": "B", "explanation": "hidden"},
    }
    async def forbidden_generate(*_args, **_kwargs):
        raise AssertionError("hidden exam answer must not reach the explanation model")
    monkeypatch.setattr("app.services.question_context_service.generate_text_async", forbidden_generate)
    result = asyncio.run(explain_question(
        interaction=interaction, user_message="答案是什么？", mode="examiner",
    ))
    assert "不能提前透露" in result
    assert "hidden" not in result
