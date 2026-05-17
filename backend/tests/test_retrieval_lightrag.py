import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.config.settings import settings
from app.main import app
from app.models.user import CurrentUser
from app.services import lightrag_service, retrieval_service


client = TestClient(app)
USER_ID = "00000000-0000-0000-0000-000000000001"
SUBJECT_ID = "00000000-0000-0000-0000-000000000010"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def use_test_user() -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=USER_ID,
        email="student@example.com",
        role="authenticated",
    )


class FakeLightRAG:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.inserted = []
        FakeLightRAG.instances.append(self)

    async def initialize_storages(self):
        self.initialized = True

    async def ainsert(self, document, ids=None, file_paths=None):
        self.inserted.append({"document": document, "ids": ids, "file_paths": file_paths})
        return "ok"

    async def aquery(self, question, param):
        self.query = {"question": question, "param": param}
        return "[material_id=mat-1 filename=notes.txt chunk_index=0]\nretrieved text"


def test_lightrag_index_uses_expected_workspace_and_storage(monkeypatch):
    FakeLightRAG.instances = []
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@localhost:5432/postgres")
    monkeypatch.setattr(settings, "lightrag_working_dir", "test_lightrag_workdir")
    monkeypatch.setattr(lightrag_service, "LightRAG", FakeLightRAG)
    monkeypatch.setattr(lightrag_service.Path, "mkdir", lambda self, parents=False, exist_ok=False: None)

    workspace = lightrag_service.index_material(
        user_id=USER_ID,
        subject_id=SUBJECT_ID,
        material_id="mat-1",
        filename="notes.txt",
        chunks=[{"chunk_index": 0, "content": "chunk text"}],
        embedding_dimension=2,
    )

    instance = FakeLightRAG.instances[0]
    assert workspace == lightrag_service.build_workspace(USER_ID, SUBJECT_ID)
    assert instance.kwargs["workspace"] == workspace
    assert instance.kwargs["graph_storage"] == "NetworkXStorage"
    assert instance.kwargs["vector_storage"] == "PGVectorStorage"
    assert instance.kwargs["embedding_func"].embedding_dim == 2
    assert "material_id=mat-1" in instance.inserted[0]["document"]


def test_lightrag_search_uses_only_context_query(monkeypatch):
    FakeLightRAG.instances = []
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@localhost:5432/postgres")
    monkeypatch.setattr(settings, "lightrag_working_dir", "test_lightrag_workdir")
    monkeypatch.setattr(lightrag_service, "LightRAG", FakeLightRAG)
    monkeypatch.setattr(lightrag_service.Path, "mkdir", lambda self, parents=False, exist_ok=False: None)

    workspace, raw_context = lightrag_service.search_context(
        user_id=USER_ID,
        subject_id=SUBJECT_ID,
        question="What is this?",
        top_k=3,
        embedding_dimension=2,
    )

    instance = FakeLightRAG.instances[0]
    assert workspace == lightrag_service.build_workspace(USER_ID, SUBJECT_ID)
    assert raw_context.endswith("retrieved text")
    assert instance.query["param"].only_need_context is True
    assert instance.query["param"].mode == "hybrid"
    assert instance.query["param"].chunk_top_k == 3


def test_extract_chunk_markers_deduplicates_citations():
    raw_context = (
        "[material_id=mat-1 filename=notes.txt chunk_index=0]\nfirst\n"
        "[material_id=mat-1 filename=notes.txt chunk_index=0]\nduplicate\n"
        "[material_id=mat-2 filename=other.pdf chunk_index=4]\nsecond"
    )

    citations = lightrag_service.extract_chunk_markers(raw_context)

    assert len(citations) == 2
    assert citations[0]["materialId"] == "mat-1"
    assert citations[0]["chunkIndex"] == 0
    assert "first" in citations[0]["chunkText"]
    assert citations[1]["filename"] == "other.pdf"


def test_retrieval_search_requires_login():
    response = client.post(
        "/retrieval/search",
        json={"subjectId": SUBJECT_ID, "question": "What should I review?"},
    )

    assert response.status_code == 401


def test_retrieval_search_returns_citations(monkeypatch):
    use_test_user()
    monkeypatch.setattr(retrieval_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(retrieval_service, "_get_subject_embedding_dimension", lambda **_: 2)
    monkeypatch.setattr(
        retrieval_service,
        "search_context",
        lambda **_: (
            "workspace-1",
            "[material_id=mat-1 filename=notes.txt chunk_index=0]\nretrieved text",
        ),
    )

    response = client.post(
        "/retrieval/search",
        json={"subjectId": SUBJECT_ID, "question": "What should I review?", "topK": 3},
    )

    assert response.status_code == 200
    assert response.json()["workspace"] == "workspace-1"
    assert response.json()["citations"][0]["materialId"] == "mat-1"
    assert response.json()["citations"][0]["chunkText"] == "retrieved text"


def test_retrieval_search_foreign_subject_returns_404(monkeypatch):
    use_test_user()

    def raise_not_found(**_kwargs):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Subject not found")

    monkeypatch.setattr(retrieval_service, "get_subject", raise_not_found)

    response = client.post(
        "/retrieval/search",
        json={"subjectId": SUBJECT_ID, "question": "What should I review?"},
    )

    assert response.status_code == 404
