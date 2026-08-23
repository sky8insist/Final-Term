import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        email="student@example.com",
        role="authenticated",
    )
    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", [
    "/api/v1/materials?subject_id=math",
    "/api/v1/artifacts?subject_id=math",
    "/api/v1/exams?subject_id=math",
    "/api/v1/chat/history/math",
    "/api/v1/study-plans/overview?subject_id=math",
])
def test_invalid_subject_id_returns_validation_error(path: str):
    response = client.get(path)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
