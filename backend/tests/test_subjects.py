from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser


client = TestClient(app)


def _user() -> CurrentUser:
    return CurrentUser(id="user-1", email="student@example.com")


def test_create_subject_forwards_external_knowledge_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.api.subjects.subject_service.create_subject",
        lambda **kwargs: captured.update(kwargs) or {"id": "subject-1"},
    )
    app.dependency_overrides[get_current_user] = _user
    try:
        response = client.post(
            "/subjects",
            json={"name": "Algorithms", "external_knowledge_enabled": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["external_knowledge_enabled"] is True


def test_update_subject_forwards_external_knowledge_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.api.subjects.subject_service.update_subject",
        lambda **kwargs: captured.update(kwargs) or {"id": "subject-1"},
    )
    app.dependency_overrides[get_current_user] = _user
    try:
        response = client.patch(
            "/subjects/subject-1",
            json={"external_knowledge_enabled": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["external_knowledge_enabled"] is True
