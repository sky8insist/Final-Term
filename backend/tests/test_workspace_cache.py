import json

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import workspace_cache_service


class FakeRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = (ttl, value)

    def get(self, key):
        row = self.values.get(key)
        return row[1] if row else None

    def ping(self):
        return True


def _user():
    return CurrentUser(id="user-1", email="student@example.com")


def test_workspace_cache_is_user_and_subject_scoped(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(workspace_cache_service, "get_redis_client", lambda: fake)

    workspace_cache_service.save_snapshot(
        user_id="user-1", resource="chat", subject_id="subject-a", data=[{"id": "one"}],
    )

    assert workspace_cache_service.load_snapshot(
        user_id="user-1", resource="chat", subject_id="subject-a",
    )["data"] == [{"id": "one"}]
    assert workspace_cache_service.load_snapshot(
        user_id="user-2", resource="chat", subject_id="subject-a",
    ) is None
    assert workspace_cache_service.load_snapshot(
        user_id="user-1", resource="chat", subject_id="subject-b",
    ) is None


def test_workspace_cache_rejects_oversized_payload(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(workspace_cache_service, "get_redis_client", lambda: fake)

    try:
        workspace_cache_service.save_snapshot(
            user_id="user-1", resource="workspace", data={"value": "x" * 1_000_001},
        )
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("Oversized snapshot was accepted")


def test_workspace_cache_api_requires_auth_and_round_trips(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(workspace_cache_service, "get_redis_client", lambda: fake)
    client = TestClient(app)

    assert client.get("/api/v1/workspace/cache/dashboard").status_code == 401

    app.dependency_overrides[get_current_user] = _user
    try:
        saved = client.put("/api/v1/workspace/cache/dashboard", json={"data": {"stats": {"studyMinutes": 30}}})
        loaded = client.get("/api/v1/workspace/cache/dashboard")
    finally:
        app.dependency_overrides.clear()

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json()["stale"] is True
    assert loaded.json()["data"]["stats"]["studyMinutes"] == 30
    assert json.loads(fake.values[next(iter(fake.values))][1])["schemaVersion"] == 1
