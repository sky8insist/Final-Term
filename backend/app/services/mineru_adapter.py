from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from app.config.settings import settings
from app.services.mineru_client import MinerUError


PARSER_NAME = "mineru-v4"
PARSER_VERSION = "1.0.0"


@dataclass(frozen=True)
class MinerUBundle:
    blocks: list[dict]
    markdown: bytes | None
    metadata: dict


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def _strings(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip()).strip()
    return ""


def _entry_text(entry: dict) -> str:
    kind = str(entry.get("type", "text"))
    if kind in {"text", "equation", "header", "footer", "page_number", "aside_text", "page_footnote"}:
        return _strings(entry.get("text"))
    if kind == "table":
        values = (entry.get("table_caption"), entry.get("table_body"), entry.get("table_footnote"))
    elif kind == "image":
        values = (entry.get("image_caption"), entry.get("image_footnote"))
    elif kind == "chart":
        values = (entry.get("chart_caption"), entry.get("content"), entry.get("chart_footnote"))
    elif kind == "list":
        values = (entry.get("list_items"),)
    elif kind == "code":
        values = (entry.get("code_caption"), entry.get("code_body"))
    else:
        values = (entry.get("text"), entry.get("content"))
    return "\n".join(part for value in values if (part := _strings(value))).strip()


def _bbox(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) >= 4:
        return {"x0": value[0], "y0": value[1], "x1": value[2], "y1": value[3]}
    return None


def _block(entry: dict, text: str, sequence: int) -> dict:
    kind = str(entry.get("type", "text"))
    if kind == "text":
        block_type = "heading" if int(entry.get("text_level") or 0) > 0 else "paragraph"
    elif kind == "equation":
        block_type = "formula"
    elif kind in {"table", "image", "chart"}:
        block_type = kind
    else:
        block_type = "paragraph"
    page_idx = entry.get("page_idx")
    page = int(page_idx) + 1 if isinstance(page_idx, int) and page_idx >= 0 else None
    identity = f"{page}:{sequence}:{kind}:{text}".encode("utf-8")
    return {
        "block_type": block_type,
        "content_text": text,
        "structured_data": {"mineruType": kind, "mineru": entry},
        "page_number": page,
        "bounding_box": _bbox(entry.get("bbox")),
        "start_time": None,
        "end_time": None,
        "sequence_index": sequence,
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "confidence": 1.0,
        "source_hash": hashlib.sha256(identity).hexdigest(),
        "metadata": {"primaryParser": True, "ocrUsed": False},
    }


def read_mineru_bundle(bundle: bytes, *, image_ocr: bool = False) -> MinerUBundle:
    if len(bundle) > settings.mineru_max_result_mb * 1024 * 1024:
        raise MinerUError("MinerU result exceeds the configured size limit", code="result_too_large")
    try:
        with ZipFile(BytesIO(bundle)) as archive:
            entries = archive.infolist()
            if any(not _safe_member(item.filename) for item in entries):
                raise MinerUError("Unsafe path found in MinerU result Zip", code="unsafe_zip")
            unpacked = sum(item.file_size for item in entries)
            if unpacked > settings.mineru_max_unpacked_mb * 1024 * 1024:
                raise MinerUError("MinerU result expands beyond the configured limit", code="zip_bomb")
            candidates = [
                item for item in entries
                if item.filename.lower().endswith("_content_list.json")
                and not item.filename.lower().endswith("_content_list_v2.json")
            ]
            if len(candidates) != 1:
                raise MinerUError("Expected one stable content_list.json in MinerU result", code="missing_content_list")
            try:
                content = json.loads(archive.read(candidates[0]).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MinerUError("MinerU content list is invalid", code="invalid_content_list") from exc
            if not isinstance(content, list):
                raise MinerUError("MinerU content list must be an array", code="invalid_content_list")
            blocks = []
            ignored = {"header", "footer", "page_number", "aside_text", "page_footnote"}
            for entry in content:
                if not isinstance(entry, dict) or str(entry.get("type")) in ignored:
                    continue
                text = _entry_text(entry)
                if text:
                    block = _block(entry, text, len(blocks))
                    block["metadata"]["ocrUsed"] = image_ocr
                    blocks.append(block)
            if not blocks:
                raise MinerUError("MinerU content list contains no usable text", code="empty_result")
            markdown_entries = [item for item in entries if item.filename.lower().endswith("full.md")]
            markdown = archive.read(markdown_entries[0]) if markdown_entries else None
            return MinerUBundle(
                blocks=blocks,
                markdown=markdown,
                metadata={
                    "contentListPath": candidates[0].filename,
                    "archiveEntries": len(entries),
                    "archiveBytes": len(bundle),
                    "unpackedBytes": unpacked,
                    "bundleSha256": hashlib.sha256(bundle).hexdigest(),
                },
            )
    except BadZipFile as exc:
        raise MinerUError("MinerU result is not a valid Zip file", code="invalid_zip") from exc
