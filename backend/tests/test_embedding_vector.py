import pytest

from app.config.settings import settings
from app.db import vector_store
from app.services import embedding_service
from app.services.embedding_service import EmbeddingError


class FakeResponse:
    def __init__(self, payload: dict, status_error: Exception | None = None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse, calls: list[dict]):
        self.response = response
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.response


def test_embedding_service_parses_openai_compatible_response(monkeypatch):
    calls = []
    response = FakeResponse(
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
    )
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "embedding_model", "Qwen/Qwen3-VL-Embedding-8B")
    monkeypatch.setattr(
        embedding_service.httpx,
        "Client",
        lambda timeout: FakeHttpClient(response, calls),
    )

    vectors = embedding_service.embed_texts(["one", "two"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert calls[0]["url"] == "https://example.test/v1/embeddings"
    assert calls[0]["json"]["model"] == "Qwen/Qwen3-VL-Embedding-8B"


def test_embedding_service_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    with pytest.raises(EmbeddingError, match="API key"):
        embedding_service.embed_texts(["text"])


def test_embedding_service_rejects_count_mismatch(monkeypatch):
    response = FakeResponse({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        embedding_service.httpx,
        "Client",
        lambda timeout: FakeHttpClient(response, []),
    )

    with pytest.raises(EmbeddingError, match="count"):
        embedding_service.embed_texts(["one", "two"])


def test_embedding_service_rejects_inconsistent_dimensions(monkeypatch):
    response = FakeResponse(
        {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3]},
            ]
        }
    )
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        embedding_service.httpx,
        "Client",
        lambda timeout: FakeHttpClient(response, []),
    )

    with pytest.raises(EmbeddingError, match="dimensions"):
        embedding_service.embed_texts(["one", "two"])


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.calls.append({"sql": sql, "params": params})


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


def test_vector_store_updates_chunks_with_user_subject_material_constraints(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr(settings, "database_url", "postgresql://example")
    monkeypatch.setattr(vector_store.psycopg, "connect", lambda _url: connection)

    count = vector_store.update_chunk_embeddings(
        user_id="user-1",
        subject_id="subject-1",
        material_id="material-1",
        chunks=[{"id": "chunk-1"}],
        embeddings=[[0.1, 0.2]],
        embedding_model="Qwen/Qwen3-VL-Embedding-8B",
    )

    assert count == 1
    assert connection.committed
    sql = cursor.calls[0]["sql"]
    assert "and user_id = %s" in sql
    assert "and subject_id = %s" in sql
    assert "and material_id = %s" in sql
    assert cursor.calls[0]["params"] == (
        "[0.1,0.2]",
        "Qwen/Qwen3-VL-Embedding-8B",
        2,
        "chunk-1",
        "user-1",
        "subject-1",
        "material-1",
    )


def test_vector_store_rejects_inconsistent_dimensions(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql://example")

    with pytest.raises(vector_store.VectorStoreError, match="dimensions"):
        vector_store.update_chunk_embeddings(
            user_id="user-1",
            subject_id="subject-1",
            material_id="material-1",
            chunks=[{"id": "chunk-1"}, {"id": "chunk-2"}],
            embeddings=[[0.1, 0.2], [0.3]],
            embedding_model="model",
        )
