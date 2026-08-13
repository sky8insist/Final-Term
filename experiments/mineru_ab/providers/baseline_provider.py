from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

from experiments.mineru_ab.config import REPOSITORY_ROOT
from experiments.mineru_ab.models import ExperimentBlock, ParseRun


BLOCK_TYPE_MAP = {
    "heading": "heading",
    "paragraph": "paragraph",
    "table": "table",
    "formula": "formula",
    "image": "image",
    "chart": "chart",
    "audio": "audio",
}


def _ensure_backend_importable() -> None:
    backend = str(REPOSITORY_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


class BaselineProvider:
    name = "baseline"

    def parse(self, path: Path, *, case_id: str, content_type: str) -> ParseRun:
        _ensure_backend_importable()
        started = perf_counter()
        try:
            from app.services.parse_service import parse_document_blocks

            raw_blocks = parse_document_blocks(
                path.read_bytes(), filename=path.name, content_type=content_type,
            )
            blocks = [
                ExperimentBlock(
                    type=BLOCK_TYPE_MAP.get(str(item.get("block_type")), "paragraph"),
                    text=str(item.get("content_text", "")),
                    sequence=int(item.get("sequence_index", index)),
                    page=item.get("page_number"),
                    bbox=item.get("bounding_box"),
                    structured_data=dict(item.get("structured_data") or {}),
                    provider=self.name,
                )
                for index, item in enumerate(raw_blocks)
            ]
            return ParseRun(
                case_id=case_id, provider=self.name, success=True,
                duration_seconds=perf_counter() - started, blocks=blocks,
                metadata={"parser": "current-project-parse_document_blocks"},
            )
        except Exception as exc:
            return ParseRun(
                case_id=case_id, provider=self.name, success=False,
                duration_seconds=perf_counter() - started,
                error_code=type(exc).__name__, error_message=str(exc),
            )

