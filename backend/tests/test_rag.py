import asyncio
import pytest
from fastapi import HTTPException

from app.config.settings import settings
from app.services import rag_service

USER_ID = "00000000-0000-0000-0000-000000000001"
SUBJECT_ID = "00000000-0000-0000-0000-000000000010"


def test_answer_with_rag_generates_answer_records_history_and_progress(monkeypatch):
    calls = []

    def fake_search_subject_context(**kwargs):
        assert kwargs["user_id"] == USER_ID
        assert kwargs["subject_id"] == SUBJECT_ID
        return {
            "subjectId": SUBJECT_ID,
            "question": "What should I review?",
            "workspace": "workspace-1",
            "rawContext": "[material_id=mat-1 filename=notes.txt chunk_index=0]\nretrieved text",
            "citations": [
                {
                    "materialId": "mat-1",
                    "filename": "notes.txt",
                    "chunkIndex": 0,
                    "chunkText": "retrieved text",
                    "score": None,
                }
            ],
        }

    async def fake_generate_text_async(prompt, **kwargs):
        assert "retrieved text" in prompt
        return "这是基于资料的答案。"

    def fake_record_qa_history(**kwargs):
        calls.append(("history", kwargs))
        assert kwargs["question"] == "What should I review?"
        assert kwargs["answer"] == "这是基于资料的答案。"
        assert kwargs["citations"][0]["sourceName"] == "notes.txt #0"
        return {"id": "assistant-msg-1"}

    def fake_increment_review_total(**kwargs):
        calls.append(("progress", kwargs))
        return {"subjectId": SUBJECT_ID, "masteredCount": 0, "totalCount": 1}

    monkeypatch.setattr(rag_service, "search_subject_context", fake_search_subject_context)
    monkeypatch.setattr(rag_service, "generate_text_async", fake_generate_text_async)
    monkeypatch.setattr(rag_service.memory_service, "record_qa_history", fake_record_qa_history)
    monkeypatch.setattr(rag_service.memory_service, "increment_review_total", fake_increment_review_total)

    result = asyncio.run(
        rag_service.answer_with_rag(
            user_id=USER_ID,
            subject_id=SUBJECT_ID,
            question="What should I review?",
        )
    )

    assert result["answer"] == "这是基于资料的答案。"
    assert result["messageId"] == "assistant-msg-1"
    assert result["citations"][0]["materialId"] == "mat-1"
    assert result["generation"]["mocked"] is False
    assert result["generation"]["grounded"] is True
    assert result["generation"]["model"] == settings.llm_model
    assert [call[0] for call in calls] == ["history", "progress"]


def test_answer_with_rag_refuses_mock_answers(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rag_service.answer_with_rag(
            user_id=USER_ID, subject_id=SUBJECT_ID, question="What is strategy?",
        ))

    assert exc_info.value.status_code == 503
    assert "真实模型未启用" in exc_info.value.detail


def test_answer_with_rag_does_not_call_llm_without_citations(monkeypatch):
    llm_called = False

    def fake_search_subject_context(**_kwargs):
        return {
            "subjectId": SUBJECT_ID,
            "question": "Unknown?",
            "workspace": "workspace-1",
            "rawContext": "",
            "citations": [],
        }

    async def fake_generate_text_async(*_args, **_kwargs):
        nonlocal llm_called
        llm_called = True
        return "should not happen"

    monkeypatch.setattr(rag_service, "search_subject_context", fake_search_subject_context)
    monkeypatch.setattr(rag_service, "generate_text_async", fake_generate_text_async)
    monkeypatch.setattr(
        rag_service.memory_service,
        "record_qa_history",
        lambda **_: {"id": "assistant-msg-1"},
    )
    monkeypatch.setattr(
        rag_service.memory_service,
        "increment_review_total",
        lambda **_: {"subjectId": SUBJECT_ID, "masteredCount": 0, "totalCount": 1},
    )

    result = asyncio.run(
        rag_service.answer_with_rag(
            user_id=USER_ID,
            subject_id=SUBJECT_ID,
            question="Unknown?",
        )
    )

    assert "资料中未找到足够依据" in result["answer"]
    assert result["citations"] == []
    assert llm_called is False
