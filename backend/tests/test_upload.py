import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.config.settings import settings
from app.main import app
from app.services.file_service import normalized_upload_content_type
from app.models.user import CurrentUser
from app.services import material_service


client = TestClient(app)


def test_upload_type_can_be_inferred_for_browser_audio_without_mime():
    from io import BytesIO
    from starlette.datastructures import Headers, UploadFile
    file = UploadFile(BytesIO(b"....ftypM4A "), filename="lecture.m4a", headers=Headers())
    assert normalized_upload_content_type(file) == "audio/x-m4a"
USER_ID = "00000000-0000-0000-0000-000000000001"
SUBJECT_ID = "00000000-0000-0000-0000-000000000010"
MATERIAL_ID = "00000000-0000-0000-0000-000000000020"


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


class FakeQuery:
    def __init__(self, db: dict, table_name: str):
        self.db = db
        self.table_name = table_name
        self.payload = None
        self.update_payload = None
        self.filters: list[tuple[str, str]] = []

    def insert(self, payload):
        self.payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, _column, desc=False):
        return self

    def execute(self):
        if self.table_name == "materials" and self.payload is not None:
            row = {
                "id": MATERIAL_ID,
                "created_at": "2026-05-17T00:00:00Z",
                "updated_at": "2026-05-17T00:00:00Z",
                **self.payload,
            }
            self.db["materials"].append(row)
            return type("Response", (), {"data": [row]})()

        if self.table_name == "lightrag_material_index" and self.payload is not None:
            row = {
                "id": "00000000-0000-0000-0000-000000000040",
                "created_at": "2026-05-17T00:00:00Z",
                "updated_at": "2026-05-17T00:00:00Z",
                **self.payload,
            }
            self.db["lightrag_material_index"].append(row)
            return type("Response", (), {"data": [row]})()

        if self.table_name == "material_chunks" and self.payload is not None:
            rows = []
            for index, payload in enumerate(self.payload):
                row = {
                    "id": f"00000000-0000-0000-0000-00000000003{index}",
                    "created_at": "2026-05-17T00:00:00Z",
                    **payload,
                }
                rows.append(row)
            self.db["material_chunks"].extend(rows)
            return type("Response", (), {"data": rows})()

        if self.table_name == "materials" and self.update_payload is not None:
            material_id = dict(self.filters).get("id")
            user_id = dict(self.filters).get("user_id")
            for row in self.db["materials"]:
                if row["id"] == material_id and row["user_id"] == user_id:
                    row.update(self.update_payload)
                    row["updated_at"] = "2026-05-17T00:00:01Z"
                    return type("Response", (), {"data": [row]})()
            return type("Response", (), {"data": []})()

        if self.table_name == "lightrag_material_index" and self.update_payload is not None:
            material_id = dict(self.filters).get("material_id")
            user_id = dict(self.filters).get("user_id")
            for row in self.db["lightrag_material_index"]:
                if row["material_id"] == material_id and row["user_id"] == user_id:
                    row.update(self.update_payload)
                    row["updated_at"] = "2026-05-17T00:00:01Z"
                    return type("Response", (), {"data": [row]})()
            return type("Response", (), {"data": []})()

        if self.table_name == "materials":
            rows = list(self.db["materials"])
            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]
            return type("Response", (), {"data": rows})()

        return type("Response", (), {"data": []})()


class FakeClient:
    def __init__(self):
        self.db = {"materials": [], "material_chunks": [], "lightrag_material_index": []}

    def table(self, name):
        assert name in self.db
        return FakeQuery(self.db, name)


@pytest.fixture
def fake_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(material_service, "get_supabase_client", lambda: fake)
    monkeypatch.setattr(
        material_service,
        "insert_content_blocks",
        lambda **kwargs: [
            {"id": f"00000000-0000-0000-0000-00000000005{index}", **block}
            for index, block in enumerate(kwargs["blocks"])
        ],
    )
    return fake


def test_upload_requires_bearer_token():
    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 401


def test_upload_rejects_unsupported_file_type(monkeypatch):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})

    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.exe", b"hello", "application/x-msdownload")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file type"


def test_upload_rejects_declared_pdf_with_non_pdf_content(monkeypatch):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})
    response = client.post(
        "/materials/upload", data={"subject_id": SUBJECT_ID},
        files={"file": ("fake.pdf", b"not actually a pdf", "application/pdf")},
    )
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


def test_upload_rejects_file_over_max_size(monkeypatch):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(settings, "max_upload_mb", 0)

    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 413


def test_upload_returns_404_for_missing_or_foreign_subject(monkeypatch):
    use_test_user()

    def raise_not_found(**_: str) -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Subject not found")

    monkeypatch.setattr(material_service, "get_subject", raise_not_found)

    response = client.post(
        "/materials/upload",
        data={"subject_id": "00000000-0000-0000-0000-000000000099"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Subject not found"


def test_upload_processes_txt_and_creates_chunks(monkeypatch, fake_client):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(material_service, "embed_texts", lambda texts: [[0.1, 0.2] for _ in texts])
    vector_calls = []

    def fake_update_chunk_embeddings(**kwargs):
        vector_calls.append(kwargs)
        return len(kwargs["chunks"])

    monkeypatch.setattr(material_service, "update_chunk_embeddings", fake_update_chunk_embeddings)
    monkeypatch.setattr(
        material_service,
        "index_material",
        lambda **kwargs: material_service.build_workspace(
            user_id=kwargs["user_id"],
            subject_id=kwargs["subject_id"],
        ),
    )

    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.txt", b"hello module four", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["material"]["status"] == "ready"
    assert response.json()["material"]["filename"] == "notes.txt"
    assert fake_client.db["materials"][0]["status"] == "ready"
    assert fake_client.db["material_chunks"][0]["content"] == "hello module four"
    assert fake_client.db["material_chunks"][0]["user_id"] == USER_ID
    assert fake_client.db["material_chunks"][0]["subject_id"] == SUBJECT_ID
    assert vector_calls[0]["embedding_model"] == settings.embedding_model
    assert vector_calls[0]["embeddings"] == [[0.1, 0.2]]
    assert fake_client.db["lightrag_material_index"][0]["status"] == "indexed"


def test_upload_marks_material_failed_when_text_is_empty(monkeypatch, fake_client):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})

    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.txt", b"   \n\n", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["material"]["status"] == "failed"
    assert response.json()["material"]["errorMessage"] == "No extractable text found in this file"
    assert fake_client.db["material_chunks"] == []


def test_upload_marks_material_failed_when_embedding_fails(monkeypatch, fake_client):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})

    def fail_embedding(_texts):
        from app.services.embedding_service import EmbeddingError

        raise EmbeddingError("Embedding API request failed")

    monkeypatch.setattr(material_service, "embed_texts", fail_embedding)

    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.txt", b"hello module five", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["material"]["status"] == "failed"
    assert response.json()["material"]["errorMessage"] == "Embedding API request failed"
    assert fake_client.db["material_chunks"][0]["content"] == "hello module five"


def test_upload_degrades_to_vector_search_when_lightrag_index_fails(monkeypatch, fake_client):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})
    monkeypatch.setattr(material_service, "embed_texts", lambda texts: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(
        material_service,
        "update_chunk_embeddings",
        lambda **kwargs: len(kwargs["chunks"]),
    )

    def fail_index(**_kwargs):
        from app.services.lightrag_service import LightRAGServiceError

        raise LightRAGServiceError("LightRAG indexing failed")

    monkeypatch.setattr(material_service, "index_material", fail_index)

    response = client.post(
        "/materials/upload",
        data={"subject_id": SUBJECT_ID},
        files={"file": ("notes.txt", b"hello module six", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["material"]["status"] == "ready"
    assert response.json()["material"]["errorMessage"] is None
    assert fake_client.db["lightrag_material_index"][0]["status"] == "failed"
    assert fake_client.db["lightrag_material_index"][0]["error_message"] == "LightRAG indexing failed"


def test_list_materials_filters_current_user_subject(monkeypatch, fake_client):
    use_test_user()
    monkeypatch.setattr(material_service, "get_subject", lambda **_: {})
    fake_client.db["materials"].append(
        {
            "id": MATERIAL_ID,
            "user_id": USER_ID,
            "subject_id": SUBJECT_ID,
            "filename": "notes.txt",
            "content_type": "text/plain",
            "file_size": 5,
            "status": "ready",
            "error_message": None,
            "created_at": "2026-05-17T00:00:00Z",
            "updated_at": "2026-05-17T00:00:00Z",
        }
    )

    response = client.get(f"/materials?subject_id={SUBJECT_ID}")

    assert response.status_code == 200
    assert response.json()[0]["subjectId"] == SUBJECT_ID
