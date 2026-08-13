from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExperimentBlock:
    type: str
    text: str
    sequence: int
    page: int | None = None
    bbox: Any = None
    structured_data: dict[str, Any] = field(default_factory=dict)
    provider: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParseRun:
    case_id: str
    provider: str
    success: bool
    duration_seconds: float
    blocks: list[ExperimentBlock] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_text:
            for block in data["blocks"]:
                block["text"] = f"<redacted:{len(block['text'])} chars>"
                block["structured_data"] = {}
        return data

