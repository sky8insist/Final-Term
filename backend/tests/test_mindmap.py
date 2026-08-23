import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mindmap.planner import MindMapValidationError, normalize_map
from app.mindmap.prompts import build_focus_question
from app.mindmap import service


client = TestClient(app)


def test_mind_map_route_requires_login_with_new_payload():
    response = client.post("/api/v1/artifacts/mind-maps", json={
        "subjectId": "subject", "mode": "question", "query": "战略和战术有什么区别？",
    })
    assert response.status_code == 401


@pytest.mark.parametrize(("mode", "query", "expected"), [
    ("question", "战略和战术有什么区别？", "战略和战术有什么区别？"),
    ("topic", "战略", "战略是什么？"),
    ("chapter", "第二章", "第二章有哪些核心知识？"),
])
def test_focus_question_modes(mode, query, expected):
    _, focus = build_focus_question(mode=mode, query=query, topic_id=None, chapter_id=None)
    assert focus.startswith(expected)


def test_planner_rejects_unsupported_non_root_node():
    with pytest.raises(MindMapValidationError):
        normalize_map({"nodes": [
            {"id": "root", "parentId": None, "label": "主题"},
            {"id": "child", "parentId": "root", "label": "无依据结论", "sourceIds": ["invented"]},
        ]}, focus_question="问题", mode="question", max_depth=3, max_nodes=20, allowed_source_ids={"c1"})


def test_service_retries_at_most_once_and_attaches_real_mastery(monkeypatch):
    monkeypatch.setattr(service, "search_subject_context", lambda **_: {
        "citations": [{"id": "c1", "filename": "notes.pdf", "chunkText": "战略决定方向"}],
        "retrieval": {"mode": "hybrid"},
    })
    monkeypatch.setattr(service, "list_mastery", lambda **_: [{"knowledge_key": "核心概念", "mastery": 0.72}])
    attempts = []

    async def fake_generate(*_args, **_kwargs):
        attempts.append(1)
        source = "invented" if len(attempts) == 1 else "c1"
        return {
            "title": "战略", "summary": "战略决定方向。",
            "nodes": [
                {"id": "root", "parentId": None, "label": "战略", "type": "root", "sourceIds": []},
                {"id": "concept", "parentId": "root", "label": "核心概念", "type": "definition", "sourceIds": [source]},
            ],
            "edges": [{"source": "root", "target": "concept", "relation": "包含"}],
        }

    class Query:
        def insert(self, payload): self.payload = payload; return self
        def select(self, _columns): return self
        def execute(self):
            return type("Response", (), {"data": [{
                "id": "artifact", "artifact_type": "mind_map", "title": self.payload["title"],
                "content": self.payload["content"], "citations": self.payload["citations"],
            }]})()

    class Db:
        def table(self, _name): return Query()

    monkeypatch.setattr(service, "generate_json_async", fake_generate)
    monkeypatch.setattr(service, "get_supabase_client", lambda: Db())
    result = asyncio.run(service.generate_mind_map(
        user_id="user", subject_id="subject", mode="topic", query="战略",
        topic_id=None, chapter_id=None, max_depth=3, include_mastery=True,
        material_ids=None, count=20,
    ))
    assert len(attempts) == 2
    assert result["content"]["focusQuestion"].startswith("战略是什么")
    assert result["content"]["nodes"][1]["mastery"] == 0.72
    assert result["content"]["edges"][0]["relation"] == "包含"

