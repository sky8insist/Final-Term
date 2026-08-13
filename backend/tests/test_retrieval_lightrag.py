import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.config.settings import settings
from app.main import app
from app.models.user import CurrentUser
from app.services import lightrag_service, retrieval_service


client = TestClient(app)
USER_ID = "00000000-0000-0000-0000-000000000001"
SUBJECT_ID = "00000000-0000-0000-0000-000000000010"


def test_offline_tokenizer_round_trip():
    tokenizer = lightrag_service._UnicodeCodepointTokenizer()
    content = "线性代数 and emoji 🧠"

    assert tokenizer.decode(tokenizer.encode(content)) == content


def test_lightrag_relative_working_dir_is_repository_relative(monkeypatch):
    monkeypatch.setattr(settings, "lightrag_working_dir", "backend/data/lightrag")

    assert lightrag_service._resolve_working_dir() == (
        lightrag_service.PROJECT_ROOT / Path("backend/data/lightrag")
    )


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


def test_extract_chunk_markers_preserves_block_location():
    citations = lightrag_service.extract_chunk_markers(
        "[material_id=mat-1 filename=lecture.pdf chunk_index=3 "
        "block_id=block-7 block_type=paragraph page_number=4 "
        "start_time=- end_time=-]\nsource text"
    )

    assert citations[0]["blockId"] == "block-7"
    assert citations[0]["blockType"] == "paragraph"
    assert citations[0]["pageNumber"] == 4
    assert citations[0]["startTime"] is None


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


def test_retrieval_degrades_to_keyword_when_lightrag_is_unavailable(monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(retrieval_service, "_get_subject_embedding_dimension", lambda **_: 2)

    def fail_lightrag(**_):
        raise lightrag_service.LightRAGServiceError("offline")

    class Rpc:
        def execute(self):
            return type("Response", (), {"data": [{
                "id": "block-1", "material_id": "mat-1", "filename": "table.pdf",
                "block_type": "table", "content_text": "第二季度销量为20",
                "structured_data": {"rows": [["Q2", "20"]]}, "page_number": 3,
                "bounding_box": {"x0": 1}, "start_time": None, "end_time": None,
                "confidence": 0.9, "rank": 0.8,
            }]})()

    class Client:
        def rpc(self, _name, _params):
            return Rpc()

    monkeypatch.setattr(retrieval_service, "search_context", fail_lightrag)
    monkeypatch.setattr(retrieval_service, "get_supabase_client", lambda: Client())
    monkeypatch.setattr(
        retrieval_service, "embed_texts",
        lambda _texts: (_ for _ in ()).throw(retrieval_service.EmbeddingError("offline")),
    )
    result = retrieval_service.search_subject_context(
        user_id=USER_ID, subject_id=SUBJECT_ID, question="第二季度销量",
        block_types=["table"],
    )
    assert result["citations"][0]["blockType"] == "table"
    assert result["citations"][0]["pageNumber"] == 3
    assert "lightrag_unavailable" in result["retrieval"]["warnings"]


def test_vector_retrieval_preserves_content_block_location(monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(retrieval_service, "_get_subject_embedding_dimension", lambda **_: 2)
    monkeypatch.setattr(retrieval_service, "search_context", lambda **_: ("workspace", ""))
    monkeypatch.setattr(retrieval_service, "get_supabase_client", lambda: type("Client", (), {
        "rpc": lambda self, *_args, **_kwargs: type("Rpc", (), {
            "execute": lambda self: type("Response", (), {"data": []})(),
        })(),
    })())
    monkeypatch.setattr(retrieval_service, "embed_texts", lambda _texts: [[0.1, 0.2]])
    monkeypatch.setattr(retrieval_service, "search_chunk_vectors", lambda **_: [{
        "id": "chunk-1", "material_id": "mat-1", "content_block_id": "block-1",
        "filename": "lecture.pdf", "chunk_index": 0, "content": "traceable text",
        "block_type": "paragraph", "page_number": 5,
        "bounding_box": {"x0": 10, "y0": 20, "x1": 100, "y1": 40},
        "start_time": None, "end_time": None,
        "metadata": {"confidence": 0.92}, "score": 0.88,
    }])

    result = retrieval_service.search_subject_context(
        user_id=USER_ID, subject_id=SUBJECT_ID, question="定位内容",
    )

    citation = result["citations"][0]
    assert citation["blockId"] == "block-1"
    assert citation["pageNumber"] == 5
    assert citation["boundingBox"]["x0"] == 10
    assert citation["confidence"] == 0.92
