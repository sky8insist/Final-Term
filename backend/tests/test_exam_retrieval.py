import asyncio

import pytest

from app.services import exam_retrieval_service
from app.services.external_search_service import ExternalSearchError


def _course_result():
    return {
        "citations": [
            {"id": "c-core", "materialId": "m1", "filename": "战略管理.pdf", "chunkText": "战略决定组织长期方向并指导资源配置。", "score": 0.92, "rrfScore": 0.03},
            {"id": "c-side", "materialId": "m2", "filename": "附录.pdf", "chunkText": "组织的日常考勤制度。", "score": 0.18, "rrfScore": 0.01},
        ],
        "retrieval": {"sources": ["vector", "keyword"], "warnings": []},
    }


def test_exam_evidence_combines_course_and_public_sources(monkeypatch):
    monkeypatch.setattr(exam_retrieval_service, "search_subject_context", lambda **_: _course_result())
    monkeypatch.setattr(exam_retrieval_service, "_knowledge_points", lambda **_: [
        {"knowledge_key": "战略作用", "title": "战略的作用", "importance": 90},
    ])

    public_queries = []

    async def public_search(query, **_kwargs):
        public_queries.append(query)
        return [{
            "title": "战略管理", "url": "https://zh.wikipedia.org/wiki/战略管理",
            "content": "战略管理帮助组织形成长期方向与竞争优势。", "publishedAt": None,
            "accessedAt": "2026-08-23T00:00:00Z", "trustLevel": "medium", "score": 0.8,
            "provider": "wikipedia",
        }]

    monkeypatch.setattr(exam_retrieval_service, "search_public_knowledge_async", public_search)
    result = asyncio.run(exam_retrieval_service.retrieve_exam_evidence(
        user_id="u", subject_id="s", topic="战略的作用", question_count=10,
        material_ids=None, knowledge_policy="course_first",
    ))
    assert result["retrieval"]["externalAttempted"] is True
    assert public_queries == ["战略"]
    assert result["retrieval"]["externalUsed"] is True
    assert result["retrieval"]["courseEvidenceCount"] >= 1
    assert result["retrieval"]["externalEvidenceCount"] == 1
    assert all("finalScore" in item and "importanceScore" in item for item in result["citations"])


def test_exam_evidence_degrades_when_public_source_is_unavailable(monkeypatch):
    monkeypatch.setattr(exam_retrieval_service, "search_subject_context", lambda **_: _course_result())
    monkeypatch.setattr(exam_retrieval_service, "_knowledge_points", lambda **_: [])

    async def unavailable(*_args, **_kwargs):
        raise ExternalSearchError("offline")

    monkeypatch.setattr(exam_retrieval_service, "search_public_knowledge_async", unavailable)
    result = asyncio.run(exam_retrieval_service.retrieve_exam_evidence(
        user_id="u", subject_id="s", topic="战略的作用", question_count=5,
        material_ids=None, knowledge_policy="course_first",
    ))
    assert result["retrieval"]["externalUsed"] is False
    assert "external_knowledge_unavailable" in result["retrieval"]["warnings"]


def test_exam_evidence_requires_indexed_course_material(monkeypatch):
    monkeypatch.setattr(exam_retrieval_service, "search_subject_context", lambda **_: {
        "citations": [], "retrieval": {"sources": [], "warnings": []},
    })
    with pytest.raises(ValueError, match="indexed course material"):
        asyncio.run(exam_retrieval_service.retrieve_exam_evidence(
            user_id="u", subject_id="s", topic="战略的作用", question_count=5,
            material_ids=None, knowledge_policy="course_only",
        ))
