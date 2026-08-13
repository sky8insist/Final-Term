from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import task_service

client = TestClient(app)


def _user():
    return CurrentUser(id="00000000-0000-0000-0000-000000000001", email="student@example.com")


def test_v1_get_task_is_user_scoped(monkeypatch):
    app.dependency_overrides[get_current_user] = _user
    captured = {}

    def fake_get_task(*, user_id: str, task_id: str):
        captured.update(user_id=user_id, task_id=task_id)
        return {
            "id": task_id, "subjectId": "subject", "materialId": "material",
            "taskType": "material_ingestion", "status": "queued", "stage": "queued",
            "progress": 0, "attempts": 0, "maxAttempts": 3,
            "errorCode": None, "errorMessage": None, "createdAt": None, "updatedAt": None,
        }

    monkeypatch.setattr(task_service, "get_task", fake_get_task)
    response = client.get("/api/v1/tasks/task-1")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured == {"user_id": _user().id, "task_id": "task-1"}
    assert response.json()["status"] == "queued"


def test_cancel_task_returns_service_result(monkeypatch):
    app.dependency_overrides[get_current_user] = _user
    monkeypatch.setattr(
        task_service, "cancel_task",
        lambda **_: {"id": "task-1", "status": "cancelled", "stage": "cancelled"},
    )
    response = client.delete("/api/v1/tasks/task-1")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_retry_requeues_material_and_clears_failure(monkeypatch):
    monkeypatch.setattr(task_service, "get_task", lambda **_: {
        "id": "task-1", "materialId": "material-1", "status": "failed",
        "attempts": 1, "maxAttempts": 3,
    })
    monkeypatch.setattr(task_service, "update_task", lambda **changes: {
        "id": changes["task_id"], "status": changes["status"], "stage": changes["stage"],
    })
    captured = {}

    class Query:
        def update(self, payload):
            captured.update(payload)
            return self
        def eq(self, *_args):
            return self
        def execute(self):
            return type("Response", (), {"data": []})()

    class Client:
        def table(self, name):
            assert name == "materials"
            return Query()

    monkeypatch.setattr(task_service, "get_supabase_client", lambda: Client())
    result = task_service.retry_task(user_id="user", task_id="task-1")
    assert result["status"] == "queued"
    assert captured == {"status": "queued", "error_message": None}
