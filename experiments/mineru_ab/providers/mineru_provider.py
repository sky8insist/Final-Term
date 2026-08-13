from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from experiments.mineru_ab.config import ExperimentSettings


class MinerUError(RuntimeError):
    def __init__(self, message: str, *, code: str = "mineru_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class UploadTicket:
    batch_id: str
    file_url: str
    trace_id: str | None = None


class MinerUProvider:
    """Minimal precise-API client with a non-bypassable no-OCR contract."""

    name = "mineru"
    terminal_states = {"done", "failed"}

    def __init__(
        self,
        settings: ExperimentSettings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        test_mode: bool = False,
    ):
        if settings.model_version != "pipeline":
            raise ValueError("MinerU no-OCR experiment requires the pipeline model")
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(90.0, connect=settings.connect_timeout_seconds),
            follow_redirects=False,
        )
        # Signed OSS/CDN transfers are more reliable without inheriting a local
        # HTTP(S)_PROXY. API control-plane calls keep the normal environment.
        self.transfer_client = client or httpx.Client(
            timeout=httpx.Timeout(90.0, connect=settings.connect_timeout_seconds),
            follow_redirects=False, trust_env=False,
        )
        self.sleep = sleep
        self.test_mode = test_mode

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
            self.transfer_client.close()

    def _authorize(self) -> dict[str, str]:
        if not self.test_mode:
            self.settings.require_live_credentials()
        if not self.settings.token:
            raise MinerUError("MinerU token is missing", code="missing_token")
        return {
            "Authorization": f"Bearer {self.settings.token}",
            "Content-Type": "application/json",
        }

    def build_upload_payload(self, *, filename: str, data_id: str) -> dict:
        payload = {
            "files": [{"name": filename, "data_id": data_id, "is_ocr": False}],
            "model_version": "pipeline",
            "language": self.settings.language,
            "enable_table": self.settings.enable_table,
            "enable_formula": self.settings.enable_formula,
        }
        self.assert_no_ocr(payload)
        return payload

    @staticmethod
    def assert_no_ocr(payload: dict) -> None:
        if payload.get("model_version") != "pipeline":
            raise MinerUError("Non-pipeline model is forbidden", code="ocr_guard")
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            raise MinerUError("Upload payload has no files", code="invalid_payload")
        if any(item.get("is_ocr") is not False for item in files):
            raise MinerUError("OCR must remain explicitly disabled", code="ocr_guard")

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise MinerUError("MinerU returned invalid JSON", code="invalid_response") from exc
        if response.status_code == 429:
            raise MinerUError("MinerU rate limit reached", code="rate_limited", retryable=True)
        if response.status_code >= 500:
            raise MinerUError("MinerU service is temporarily unavailable", code="remote_5xx", retryable=True)
        if response.status_code >= 400:
            raise MinerUError(f"MinerU HTTP {response.status_code}", code="remote_http")
        if not isinstance(body, dict) or body.get("code") != 0:
            code = str(body.get("code", "invalid_response")) if isinstance(body, dict) else "invalid_response"
            message = str(body.get("msg", "MinerU request failed")) if isinstance(body, dict) else "MinerU request failed"
            retryable = code in {"-10001", "-60007", "-60008", "-60009", "-60010"}
            raise MinerUError(message, code=code, retryable=retryable)
        return body

    def request_upload(self, *, filename: str, data_id: str) -> UploadTicket:
        payload = self.build_upload_payload(filename=filename, data_id=data_id)
        response = None
        last_error = None
        for attempt in range(self.settings.transport_retries):
            try:
                response = self.client.post(
                    f"{self.settings.base_url}/api/v4/file-urls/batch",
                    headers=self._authorize(), json=payload,
                )
                break
            except httpx.RequestError as exc:
                last_error = exc
                if attempt + 1 < self.settings.transport_retries:
                    self.sleep(min(2 ** attempt, 5))
        if response is None:
            raise MinerUError(
                "Unable to request a MinerU upload ticket", code="network_error", retryable=True,
            ) from last_error
        body = self._json(response)
        data = body.get("data") or {}
        urls = data.get("file_urls") or []
        if not data.get("batch_id") or len(urls) != 1:
            raise MinerUError("MinerU upload ticket is incomplete", code="invalid_response")
        return UploadTicket(
            batch_id=str(data["batch_id"]), file_url=str(urls[0]),
            trace_id=body.get("trace_id"),
        )

    def upload_file(self, ticket: UploadTicket, path: Path) -> None:
        parsed = urlparse(ticket.file_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise MinerUError("MinerU upload URL must use HTTPS", code="unsafe_upload_url")
        response = None
        last_error = None
        for attempt in range(self.settings.transport_retries):
            try:
                with path.open("rb") as stream:
                    response = self.transfer_client.put(ticket.file_url, content=stream)
                break
            except httpx.RequestError as exc:
                last_error = exc
                if attempt + 1 < self.settings.transport_retries:
                    self.sleep(min(2 ** attempt, 5))
        if response is None:
            raise MinerUError(
                "Unable to upload the file to MinerU object storage",
                code="network_error", retryable=True,
            ) from last_error
        if response.status_code not in {200, 201}:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise MinerUError(
                f"MinerU signed upload failed with HTTP {response.status_code}",
                code="upload_failed", retryable=retryable,
            )

    def query_batch(self, batch_id: str) -> dict:
        response = None
        last_error = None
        for attempt in range(self.settings.transport_retries):
            try:
                response = self.client.get(
                    f"{self.settings.base_url}/api/v4/extract-results/batch/{batch_id}",
                    headers=self._authorize(),
                )
                break
            except httpx.RequestError as exc:
                last_error = exc
                if attempt + 1 < self.settings.transport_retries:
                    self.sleep(min(2 ** attempt, 5))
        if response is None:
            raise MinerUError(
                "Unable to query the MinerU batch", code="network_error", retryable=True,
            ) from last_error
        return self._json(response)

    def wait_for_result(self, batch_id: str) -> dict:
        started = time.monotonic()
        while time.monotonic() - started < self.settings.timeout_seconds:
            body = self.query_batch(batch_id)
            results = (body.get("data") or {}).get("extract_result") or []
            if len(results) != 1:
                raise MinerUError("Expected exactly one MinerU batch result", code="invalid_response")
            result = results[0]
            state = result.get("state")
            if state == "done":
                if not result.get("full_zip_url"):
                    raise MinerUError("Completed MinerU result has no Zip URL", code="invalid_response")
                return result
            if state == "failed":
                raise MinerUError(
                    str(result.get("err_msg") or "MinerU conversion failed"),
                    code="remote_parse_failed",
                )
            if state not in {"waiting-file", "pending", "running", "converting"}:
                raise MinerUError(f"Unknown MinerU state: {state}", code="invalid_response")
            self.sleep(self.settings.poll_interval_seconds)
        raise MinerUError("MinerU conversion timed out", code="timeout", retryable=True)

    def download_result(self, url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise MinerUError("MinerU result URL must use HTTPS", code="unsafe_result_url")
        try:
            with self.transfer_client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise MinerUError(
                        f"MinerU result download failed with HTTP {response.status_code}",
                        code="result_download_failed", retryable=response.status_code >= 500,
                    )
                buffer = bytearray()
                for chunk in response.iter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > self.settings.max_result_bytes:
                        raise MinerUError("MinerU result exceeds the configured size limit", code="result_too_large")
        except httpx.RequestError as exc:
            raise MinerUError("Unable to download the MinerU result", code="network_error", retryable=True) from exc
        return bytes(buffer)
