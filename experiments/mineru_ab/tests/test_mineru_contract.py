import json

import httpx

from experiments.mineru_ab.config import EXPERIMENT_ROOT
from experiments.mineru_ab.config import ExperimentSettings
from experiments.mineru_ab.providers.mineru_provider import MinerUProvider


def test_upload_contract_forces_pipeline_and_no_ocr():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={
                "code": 0, "msg": "ok", "trace_id": "trace-1",
                "data": {"batch_id": "batch-1", "file_urls": ["https://upload.example/file"]},
            })
        if request.method == "PUT":
            captured["put_content_type"] = request.headers.get("content-type")
            return httpx.Response(200)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = ExperimentSettings(token="test-token")
    provider = MinerUProvider(settings, client=client, test_mode=True)
    ticket = provider.request_upload(filename="sample.pdf", data_id="material-1")
    sample = EXPERIMENT_ROOT / "README.md"
    provider.upload_file(ticket, sample)

    assert captured["payload"]["model_version"] == "pipeline"
    assert captured["payload"]["files"][0]["is_ocr"] is False
    assert captured["headers"]["authorization"] == "Bearer test-token"
    assert captured["put_content_type"] is None


def test_query_contract_maps_completed_batch():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/v4/extract-results/batch/batch-1")
        return httpx.Response(200, json={
            "code": 0, "msg": "ok",
            "data": {"batch_id": "batch-1", "extract_result": [{
                "file_name": "sample.pdf", "state": "done",
                "full_zip_url": "https://download.example/result.zip",
            }]},
        })

    provider = MinerUProvider(
        ExperimentSettings(token="test-token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        test_mode=True,
    )
    result = provider.wait_for_result("batch-1")
    assert result["state"] == "done"


def test_upload_retries_same_ticket_after_transport_error():
    # Use the existing experiment README so no temporary filesystem is needed.
    calls = {"put": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            calls["put"] += 1
            if calls["put"] == 1:
                raise httpx.ConnectTimeout("temporary timeout", request=request)
            return httpx.Response(200)
        raise AssertionError("Only the signed upload is expected")

    settings = ExperimentSettings(token="test-token", transport_retries=2)
    provider = MinerUProvider(
        settings, client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None, test_mode=True,
    )
    from experiments.mineru_ab.config import EXPERIMENT_ROOT
    from experiments.mineru_ab.providers.mineru_provider import UploadTicket
    provider.upload_file(UploadTicket("batch", "https://upload.example/file"), EXPERIMENT_ROOT / "README.md")
    assert calls["put"] == 2
