from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_is_available_on_legacy_route():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "apiVersion": "v1"}
    assert response.headers["X-Request-ID"]


def test_v1_validation_error_uses_stable_contract():
    response = client.post(
        "/api/v1/retrieval/search",
        json={},
        headers={"X-Request-ID": "baseline-test"},
    )

    assert response.status_code in {401, 422}
    body = response.json()
    assert body["success"] is False
    assert body["error"]["requestId"] == "baseline-test"
    assert response.headers["X-Request-ID"] == "baseline-test"


def test_only_versioned_business_routes_are_published():
    paths = set(app.openapi()["paths"])

    assert "/api/v1/subjects" in paths
    assert "/subjects" not in paths
    assert not any(path.startswith("/api/workbench") for path in paths)


def test_removed_compatibility_routes_stay_removed():
    paths = set(app.openapi()["paths"])

    assert "/api/v1/outline/generate" not in paths
    assert "/api/v1/quiz/generate" not in paths
    assert "/api/v1/exams/attempts" not in paths
    assert "/api/v1/exam-attempts" in paths
    assert "/api/v1/study-plans" not in paths
    assert "post" not in app.openapi()["paths"]["/api/v1/exams"]
    assert "post" in app.openapi()["paths"]["/api/v1/exams/generations"]
    assert "post" in app.openapi()["paths"]["/api/v1/study-plans/generations"]
