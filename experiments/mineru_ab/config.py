from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path


EXPERIMENT_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = EXPERIMENT_ROOT.parents[1]


def _bool(name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_experiment_env(path: Path | None = None) -> None:
    """Load only MINERU_AB_* values, preferring the experiment-local .env."""
    candidates = [path] if path else [EXPERIMENT_ROOT / ".env", REPOSITORY_ROOT / ".env"]
    env_path = next((candidate for candidate in candidates if candidate and candidate.exists()), None)
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("MINERU_AB_"):
            environ.setdefault(key, value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class ExperimentSettings:
    live: bool = False
    token: str = ""
    base_url: str = "https://mineru.net"
    model_version: str = "pipeline"
    language: str = "ch"
    enable_table: bool = True
    enable_formula: bool = True
    poll_interval_seconds: float = 5.0
    timeout_seconds: float = 900.0
    connect_timeout_seconds: float = 60.0
    transport_retries: int = 3
    max_result_bytes: int = 300 * 1024 * 1024
    max_unpacked_bytes: int = 600 * 1024 * 1024
    pdf_sample_pages: int = 5
    min_text_chars_per_page: int = 20

    @classmethod
    def from_env(cls) -> "ExperimentSettings":
        load_experiment_env()
        model = environ.get("MINERU_AB_MODEL_VERSION", "pipeline").strip()
        if model != "pipeline":
            raise ValueError("The no-OCR experiment only permits model_version=pipeline")
        return cls(
            live=_bool("MINERU_AB_LIVE", False),
            token=environ.get("MINERU_AB_TOKEN", "").strip(),
            base_url=environ.get("MINERU_AB_BASE_URL", "https://mineru.net").rstrip("/"),
            model_version=model,
            language=environ.get("MINERU_AB_LANGUAGE", "ch").strip() or "ch",
            enable_table=_bool("MINERU_AB_ENABLE_TABLE", True),
            enable_formula=_bool("MINERU_AB_ENABLE_FORMULA", True),
            poll_interval_seconds=float(environ.get("MINERU_AB_POLL_INTERVAL_SECONDS", "5")),
            timeout_seconds=float(environ.get("MINERU_AB_TIMEOUT_SECONDS", "900")),
            connect_timeout_seconds=float(environ.get("MINERU_AB_CONNECT_TIMEOUT_SECONDS", "60")),
            transport_retries=max(int(environ.get("MINERU_AB_TRANSPORT_RETRIES", "3")), 1),
            max_result_bytes=int(environ.get("MINERU_AB_MAX_RESULT_MB", "300")) * 1024 * 1024,
            max_unpacked_bytes=int(environ.get("MINERU_AB_MAX_UNPACKED_MB", "600")) * 1024 * 1024,
            pdf_sample_pages=int(environ.get("MINERU_AB_PDF_SAMPLE_PAGES", "5")),
            min_text_chars_per_page=int(environ.get("MINERU_AB_MIN_TEXT_CHARS_PER_PAGE", "20")),
        )

    def require_live_credentials(self) -> None:
        if not self.live:
            raise RuntimeError("Live MinerU calls are disabled; set MINERU_AB_LIVE=true explicitly")
        if not self.token:
            raise RuntimeError("MINERU_AB_TOKEN is required for a live MinerU run")
