from app.main import app


def test_v3_run_and_resume_endpoints_are_mounted():
    paths = app.openapi()["paths"]
    assert "/api/v3/runs" in paths
    assert "/api/v3/runs/{thread_id}" in paths
    assert "/api/v3/runs/{thread_id}/resume" in paths
    assert "/api/v3/runs/stream" in paths
