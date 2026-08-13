from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from experiments.mineru_ab.models import ExperimentBlock
from experiments.mineru_ab.providers.mineru_provider import MinerUError


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not path.is_absolute() and ".." not in path.parts


def read_mineru_bundle(
    bundle: bytes, *, max_result_bytes: int, max_unpacked_bytes: int,
) -> tuple[list[dict], str | None, dict]:
    if len(bundle) > max_result_bytes:
        raise MinerUError("MinerU result exceeds the configured size limit", code="result_too_large")
    try:
        with ZipFile(BytesIO(bundle)) as archive:
            entries = archive.infolist()
            if any(not _safe_member(item.filename) for item in entries):
                raise MinerUError("Unsafe path found in MinerU result Zip", code="unsafe_zip")
            total_size = sum(item.file_size for item in entries)
            if total_size > max_unpacked_bytes:
                raise MinerUError("MinerU result expands beyond the configured limit", code="zip_bomb")
            candidates = [
                item for item in entries
                if item.filename.lower().endswith("_content_list.json")
                and not item.filename.lower().endswith("_content_list_v2.json")
            ]
            if len(candidates) != 1:
                raise MinerUError("Expected one stable content_list.json in MinerU result", code="missing_content_list")
            raw = archive.read(candidates[0])
            try:
                content = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MinerUError("MinerU content list is invalid", code="invalid_content_list") from exc
            if not isinstance(content, list):
                raise MinerUError("MinerU content list must be an array", code="invalid_content_list")
            markdown_entries = [item for item in entries if item.filename.lower().endswith("full.md")]
            markdown = archive.read(markdown_entries[0]).decode("utf-8") if markdown_entries else None
            metadata = {
                "contentListPath": candidates[0].filename,
                "archiveEntries": len(entries),
                "archiveBytes": len(bundle),
                "unpackedBytes": total_size,
                "bundleSha256": hashlib.sha256(bundle).hexdigest(),
            }
            return content, markdown, metadata
    except BadZipFile as exc:
        raise MinerUError("MinerU result is not a valid Zip file", code="invalid_zip") from exc


def _join_strings(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip()).strip()
    return ""


def _entry_text(entry: dict) -> str:
    kind = str(entry.get("type", "text"))
    if kind in {"text", "equation", "header", "footer", "page_number", "aside_text", "page_footnote"}:
        return _join_strings(entry.get("text"))
    if kind == "table":
        parts = [
            _join_strings(entry.get("table_caption")),
            _join_strings(entry.get("table_body")),
            _join_strings(entry.get("table_footnote")),
        ]
        return "\n".join(part for part in parts if part).strip()
    if kind == "image":
        return "\n".join(filter(None, [
            _join_strings(entry.get("image_caption")),
            _join_strings(entry.get("image_footnote")),
        ])).strip()
    if kind == "chart":
        return "\n".join(filter(None, [
            _join_strings(entry.get("chart_caption")),
            _join_strings(entry.get("content")),
            _join_strings(entry.get("chart_footnote")),
        ])).strip()
    if kind == "list":
        return _join_strings(entry.get("list_items"))
    if kind == "code":
        return "\n".join(filter(None, [
            _join_strings(entry.get("code_caption")),
            _join_strings(entry.get("code_body")),
        ])).strip()
    return _join_strings(entry.get("text") or entry.get("content"))


def adapt_content_list(entries: list[dict]) -> list[ExperimentBlock]:
    blocks: list[ExperimentBlock] = []
    ignored_auxiliary = {"header", "footer", "page_number", "aside_text", "page_footnote"}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type", "text"))
        if kind in ignored_auxiliary:
            continue
        text = _entry_text(entry)
        if not text:
            continue
        if kind == "text":
            block_type = "heading" if int(entry.get("text_level") or 0) > 0 else "paragraph"
        elif kind == "equation":
            block_type = "formula"
        elif kind in {"table", "image", "chart"}:
            block_type = kind
        else:
            block_type = "paragraph"
        page_idx = entry.get("page_idx")
        blocks.append(ExperimentBlock(
            type=block_type,
            text=text,
            sequence=len(blocks),
            page=int(page_idx) + 1 if isinstance(page_idx, int) and page_idx >= 0 else None,
            bbox=entry.get("bbox"),
            structured_data={"mineruType": kind, "raw": entry},
            provider="mineru",
        ))
    if not blocks:
        raise MinerUError("MinerU content list contains no usable text", code="empty_result")
    return blocks

