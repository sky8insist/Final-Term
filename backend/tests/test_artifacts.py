import json
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services import artifact_service

client = TestClient(app)


MIND_MAP = {
    "title": "Linear Algebra",
    "nodes": [
        {"id": "root", "parentId": None, "title": "Matrix", "order": 0},
        {"id": "child", "parentId": "root", "title": "Eigenvalue", "order": 0},
    ],
}


def test_artifact_routes_require_login():
    assert client.get("/api/v1/artifacts?subject_id=subject").status_code == 401
    assert client.post("/api/v1/artifacts", json={
        "subjectId": "subject", "artifactType": "mind_map",
    }).status_code == 401
    # Typed routes infer artifactType and therefore must not require it.
    assert client.post("/api/v1/artifacts/mind-maps", json={
        "subjectId": "subject",
    }).status_code == 401


def test_mind_map_requires_exactly_one_root():
    with pytest.raises(HTTPException):
        artifact_service._validate_mind_map({
            "nodes": [
                {"id": "a", "parentId": None, "title": "A"},
                {"id": "b", "parentId": None, "title": "B"},
            ],
        })


def test_mind_map_rejects_unknown_parent():
    with pytest.raises(HTTPException):
        artifact_service._validate_mind_map({
            "nodes": [{"id": "a", "parentId": "missing", "title": "A"}],
        })


def test_mind_map_rejects_disconnected_cycle():
    with pytest.raises(HTTPException):
        artifact_service._validate_mind_map({"nodes": [
            {"id": "root", "parentId": None, "title": "Root"},
            {"id": "a", "parentId": "b", "title": "A"},
            {"id": "b", "parentId": "a", "title": "B"},
        ]})


def test_mind_map_exports_json_markdown_mermaid_svg_png_jpg_and_pdf(monkeypatch):
    monkeypatch.setattr(artifact_service, "get_artifact", lambda **_: {
        "id": "artifact", "artifact_type": "mind_map", "content": MIND_MAP,
    })
    expected = {
        "json": "application/json", "markdown": "text/markdown; charset=utf-8",
        "mermaid": "text/plain; charset=utf-8", "svg": "image/svg+xml", "png": "image/png",
        "jpg": "image/jpeg", "pdf": "application/pdf",
    }
    for export_format, media_type in expected.items():
        data, actual_type, filename = artifact_service.export_artifact(
            user_id="user", artifact_id="artifact", export_format=export_format,
        )
        assert data
        assert actual_type == media_type
        assert filename.endswith("." + ("md" if export_format == "markdown" else "mmd" if export_format == "mermaid" else export_format))
    assert json.loads(artifact_service.export_artifact(
        user_id="user", artifact_id="artifact", export_format="json",
    )[0])["nodes"][1]["title"] == "Eigenvalue"


def test_artifact_generation_rewrites_invalid_citations(monkeypatch):
    monkeypatch.setattr(artifact_service, "search_subject_context", lambda **_: {
        "citations": [{"id": "c1", "filename": "notes.txt", "chunkText": "矩阵定义"}],
    })
    attempts = []

    async def fake_generate(_prompt):
        attempts.append(_prompt)
        citation = "invented" if len(attempts) == 1 else "c1"
        return {
            "title": "矩阵",
            "nodes": [{"id": "root", "parentId": None, "title": "矩阵",
                       "citationIds": [citation], "order": 0}],
        }

    class Query:
        def insert(self, payload):
            self.payload = payload
            return self
        def select(self, _columns):
            return self
        def execute(self):
            return type("Response", (), {"data": [{
                "id": "artifact", "artifact_type": "mind_map",
                "title": self.payload["title"], "content": self.payload["content"],
                "citations": self.payload["citations"], "version": 1,
            }]})()

    class Client:
        def table(self, _name):
            return Query()

    monkeypatch.setattr(artifact_service, "generate_json_async", fake_generate)
    monkeypatch.setattr(artifact_service, "get_supabase_client", lambda: Client())
    result = asyncio.run(artifact_service.generate_artifact(
        user_id="user", subject_id="subject", artifact_type="mind_map",
        scope=None, material_ids=None, mode="knowledge", count=10,
    ))
    assert len(attempts) == 2
    assert result["content"]["nodes"][0]["citationIds"] == ["c1"]
