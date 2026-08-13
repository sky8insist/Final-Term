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
