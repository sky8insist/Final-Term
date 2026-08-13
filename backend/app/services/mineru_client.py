from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import httpx

from app.config.settings import settings


class MinerUError(RuntimeError):
    def __init__(self, message: str, *, code: str = "mineru_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class MinerUUploadTicket:
    batch_id: str
    file_url: str
    trace_id: str | None = None


class MinerUClient:
    """Client for MinerU's v4 local-file upload API.

    The API control plane inherits the process proxy configuration. Signed
    object-storage transfers intentionally do not, because local HTTPS proxies
    commonly invalidate or rewrite those signatures.
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transfer_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._owns_clients = client is None and transfer_client is None
        timeout = httpx.Timeout(90.0, connect=15.0)
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self.transfer_client = transfer_client or httpx.Client(
            timeout=timeout, follow_redirects=False, trust_env=False,
        )
        self.sleep = sleep

    def close(self) -> None:
        if self._owns_clients:
            self.client.close()
            self.transfer_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @staticmethod
    def _safe_https_url(url: str, *, label: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise MinerUError(f"MinerU {label} URL must use HTTPS", code="unsafe_url")
        return url

    @staticmethod
    def _decode(response: httpx.Response) -> dict:
        if response.status_code == 429:
            raise MinerUError("MinerU rate limit reached", code="rate_limited", retryable=True)
        if response.status_code >= 500:
            raise MinerUError("MinerU service is temporarily unavailable", code="remote_5xx", retryable=True)
        if response.status_code >= 400:
            raise MinerUError(f"MinerU HTTP {response.status_code}", code="remote_http")
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise MinerUError("MinerU returned invalid JSON", code="invalid_response") from exc
        if not isinstance(body, dict) or body.get("code") != 0:
            code = str(body.get("code", "invalid_response")) if isinstance(body, dict) else "invalid_response"
            message = str(body.get("msg", "MinerU request failed")) if isinstance(body, dict) else "MinerU request failed"
            raise MinerUError(message, code=code, retryable=code in {"-10001", "-60007", "-60008", "-60009", "-60010"})
        return body

    def _headers(self) -> dict[str, str]:
        if not settings.mineru_api_token:
            raise MinerUError("MinerU API token is not configured", code="missing_token")
        return {
            "Authorization": f"Bearer {settings.mineru_api_token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(max(settings.mineru_transport_retries, 1)):
            try:
                return self.client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt + 1 < settings.mineru_transport_retries:
                    self.sleep(min(2 ** attempt, 5))
        raise MinerUError("Unable to contact MinerU", code="network_error", retryable=True) from last_error

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        attempts = max(settings.mineru_transport_retries, 1)
        last_error: MinerUError | None = None
        for attempt in range(attempts):
            try:
                return self._decode(self._request(method, url, **kwargs))
            except MinerUError as exc:
                last_error = exc
                if not exc.retryable or attempt + 1 >= attempts:
                    raise
                self.sleep(min(2 ** attempt, 5))
        raise last_error or MinerUError("MinerU request failed")

    def request_upload(self, *, filename: str, data_id: str, is_ocr: bool) -> MinerUUploadTicket:
        if settings.mineru_model_version not in {"pipeline", "vlm"}:
            raise MinerUError("Unsupported MinerU model version", code="invalid_configuration")
        payload = {
            "files": [{"name": filename, "data_id": data_id, "is_ocr": bool(is_ocr)}],
            "model_version": settings.mineru_model_version,
            "language": settings.mineru_language,
            "enable_table": settings.mineru_enable_table,
            "enable_formula": settings.mineru_enable_formula,
        }
        body = self._request_json(
            "POST", f"{settings.mineru_base_url.rstrip('/')}/api/v4/file-urls/batch",
            headers=self._headers(), json=payload,
        )
        data = body.get("data") or {}
        urls = data.get("file_urls") or []
        if not data.get("batch_id") or len(urls) != 1:
            raise MinerUError("MinerU upload ticket is incomplete", code="invalid_response")
        return MinerUUploadTicket(
            batch_id=str(data["batch_id"]),
            file_url=self._safe_https_url(str(urls[0]), label="upload"),
            trace_id=body.get("trace_id"),
        )

    def upload_bytes(self, ticket: MinerUUploadTicket, data: bytes) -> None:
        last_error: Exception | None = None
        for attempt in range(max(settings.mineru_transport_retries, 1)):
            try:
                # MinerU explicitly requires no Content-Type on signed uploads.
                response = self.transfer_client.put(ticket.file_url, content=data)
                if response.status_code in {200, 201, 204}:
                    return
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt + 1 >= settings.mineru_transport_retries:
                    raise MinerUError(
                        f"MinerU signed upload failed with HTTP {response.status_code}",
                        code="upload_failed", retryable=retryable,
                    )
            except httpx.RequestError as exc:
                last_error = exc
                if attempt + 1 >= settings.mineru_transport_retries:
                    break
            self.sleep(min(2 ** attempt, 5))
        raise MinerUError(
            "Unable to upload the file to MinerU object storage",
            code="network_error", retryable=True,
        ) from last_error

    def query_batch(self, batch_id: str) -> dict:
        return self._request_json(
            "GET",
            f"{settings.mineru_base_url.rstrip('/')}/api/v4/extract-results/batch/{batch_id}",
            headers=self._headers(),
        )

    def wait_for_result(self, batch_id: str, *, on_state: Callable[[str], None] | None = None) -> dict:
        started = time.monotonic()
        while time.monotonic() - started < settings.mineru_timeout_seconds:
            body = self.query_batch(batch_id)
            results = (body.get("data") or {}).get("extract_result") or []
            if len(results) != 1:
                raise MinerUError("Expected exactly one MinerU batch result", code="invalid_response")
            result = results[0]
            state = str(result.get("state", ""))
            if on_state:
                on_state(state)
            if state == "done":
                if not result.get("full_zip_url"):
                    raise MinerUError("Completed MinerU result has no Zip URL", code="invalid_response")
                return result
            if state == "failed":
                raise MinerUError(str(result.get("err_msg") or "MinerU conversion failed"), code="remote_parse_failed")
            if state not in {"waiting-file", "pending", "running", "converting"}:
                raise MinerUError(f"Unknown MinerU state: {state}", code="invalid_response")
            self.sleep(max(settings.mineru_poll_interval_seconds, 0.1))
        raise MinerUError("MinerU conversion timed out", code="timeout", retryable=True)

    def download_result(self, url: str) -> bytes:
        self._safe_https_url(url, label="result")
        attempts = max(settings.mineru_transport_retries, 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with self.transfer_client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        error = MinerUError(
                            f"MinerU result download failed with HTTP {response.status_code}",
                            code="result_download_failed",
                            retryable=response.status_code == 429 or response.status_code >= 500,
                        )
                        if not error.retryable:
                            raise error
                        last_error = error
                    else:
                        result = bytearray()
                        limit = settings.mineru_max_result_mb * 1024 * 1024
                        for chunk in response.iter_bytes():
                            result.extend(chunk)
                            if len(result) > limit:
                                raise MinerUError("MinerU result exceeds the configured size limit", code="result_too_large")
                        return bytes(result)
            except httpx.RequestError as exc:
                last_error = exc
            if attempt + 1 < attempts:
                self.sleep(min(2 ** attempt, 5))
        raise MinerUError("Unable to download the MinerU result", code="network_error", retryable=True) from last_error
