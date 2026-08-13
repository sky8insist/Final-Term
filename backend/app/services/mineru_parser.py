from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config.settings import settings
from app.services.mineru_adapter import MinerUBundle, read_mineru_bundle
from app.services.mineru_client import MinerUClient, MinerUError
from app.services.parse_service import (
    AUDIO_CONTENT_TYPES,
    DOCX_CONTENT_TYPE,
    IMAGE_CONTENT_TYPES,
    PDF_CONTENT_TYPE,
    PPTX_CONTENT_TYPE,
    TXT_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    DocumentParseError,
    parse_document_blocks,
    parse_native_document_blocks,
)


MINERU_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp",
}
NATIVE_QUALITY_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx"}
LOCAL_ONLY_SUFFIXES = {".txt", ".mp3", ".wav", ".m4a"}


@dataclass
class ParsedMaterial:
    blocks: list[dict]
    provider: str
    bundle: bytes | None = None
    markdown: bytes | None = None
    metadata: dict | None = None


def uses_mineru(*, filename: str, content_type: str) -> bool:
    suffix = Path(filename).suffix.lower()
    if content_type == TXT_CONTENT_TYPE or content_type in AUDIO_CONTENT_TYPES or suffix in LOCAL_ONLY_SUFFIXES:
        return False
    return suffix in MINERU_SUFFIXES or content_type in IMAGE_CONTENT_TYPES or content_type in {
        PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE, PPTX_CONTENT_TYPE, XLSX_CONTENT_TYPE,
        "application/msword", "application/vnd.ms-powerpoint", "application/vnd.ms-excel",
    }


def _normalized_characters(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", text).casefold()


def _coverage(reference: str, candidate: str) -> float:
    expected = Counter(_normalized_characters(reference))
    if not expected:
        return 1.0
    actual = Counter(_normalized_characters(candidate))
    return sum(min(count, actual[char]) for char, count in expected.items()) / sum(expected.values())


def _text(blocks: list[dict]) -> str:
    return "\n".join(
        str(block.get("content_text", ""))
        for block in blocks
        if block.get("block_type") in {"paragraph", "heading", "table", "formula"}
    )


def _tag_fallback(block: dict, reason: str) -> dict:
    tagged = dict(block)
    tagged["metadata"] = {
        **block.get("metadata", {}),
        "fallbackParser": True,
        "fallbackReason": reason,
        "primaryProvider": "mineru-v4",
    }
    return tagged


def _apply_native_quality_gate(primary: list[dict], native: list[dict]) -> tuple[list[dict], dict]:
    if not native:
        return primary, {"nativeCoverage": None, "fallbackPages": []}
    overall = _coverage(_text(native), _text(primary))
    fallback_pages: list[int] = []
    native_pages = sorted({int(block["page_number"]) for block in native if block.get("page_number")})
    if native_pages:
        merged: list[dict] = []
        all_pages = sorted({
            int(block["page_number"]) for block in [*primary, *native] if block.get("page_number")
        })
        no_page = [block for block in primary if not block.get("page_number")]
        merged.extend(no_page)
        for page in all_pages:
            primary_page = [block for block in primary if block.get("page_number") == page]
            native_page = [block for block in native if block.get("page_number") == page]
            recall = _coverage(_text(native_page), _text(primary_page))
            if native_page and recall < settings.mineru_page_coverage_threshold:
                fallback_pages.append(page)
                # Retain MinerU's tables, figures and formula structure while
                # replacing only incomplete native text on the affected page.
                inserted = False
                for block in primary_page:
                    if block.get("block_type") in {"paragraph", "heading"}:
                        if not inserted:
                            merged.extend(_tag_fallback(item, "low_page_coverage") for item in native_page)
                            inserted = True
                        continue
                    merged.append(block)
                if not inserted:
                    merged.extend(_tag_fallback(item, "low_page_coverage") for item in native_page)
            else:
                merged.extend(primary_page)
    elif overall < settings.mineru_native_coverage_threshold:
        primary_non_text = [block for block in primary if block.get("block_type") not in {"paragraph", "heading"}]
        native_text = [block for block in native if block.get("block_type") in {"paragraph", "heading"}]
        native_tables = [] if any(block.get("block_type") == "table" for block in primary_non_text) else [
            block for block in native if block.get("block_type") == "table"
        ]
        merged = [
            *primary_non_text,
            *(_tag_fallback(block, "low_document_coverage") for block in [*native_text, *native_tables]),
        ]
    else:
        merged = primary
    for sequence, block in enumerate(merged):
        block["sequence_index"] = sequence
    return merged, {"nativeCoverage": round(overall, 4), "fallbackPages": fallback_pages}


def _local_fallback(
    data: bytes, *, filename: str, content_type: str, reason: str,
) -> ParsedMaterial:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".pptx", ".xlsx"}:
            blocks = parse_native_document_blocks(data, filename=filename, content_type=content_type)
        else:
            blocks = parse_document_blocks(data, filename=filename, content_type=content_type)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("Both MinerU and the local fallback parser failed") from exc
    for block in blocks:
        block["metadata"] = {
            **block.get("metadata", {}), "fallbackParser": True,
            "fallbackReason": reason, "primaryProvider": "mineru-v4",
        }
    return ParsedMaterial(
        blocks=blocks, provider="local-fallback",
        metadata={"fallbackReason": reason, "qualityGate": None},
    )


def parse_material(
    data: bytes,
    *,
    filename: str,
    content_type: str,
    material_id: str,
    resume_batch_id: str | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> ParsedMaterial:
    if not uses_mineru(filename=filename, content_type=content_type):
        return ParsedMaterial(
            blocks=parse_document_blocks(data, filename=filename, content_type=content_type),
            provider="local",
        )
    if not settings.enable_mineru:
        if settings.mineru_enable_local_fallback:
            return _local_fallback(data, filename=filename, content_type=content_type, reason="mineru_disabled")
        raise DocumentParseError("MinerU parsing is disabled")

    suffix = Path(filename).suffix.lower()
    image_ocr = content_type in IMAGE_CONTENT_TYPES or suffix in {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
    batch_id = resume_batch_id
    try:
        with MinerUClient() as client:
            if not batch_id:
                data_id = re.sub(r"[^0-9A-Za-z_.-]", "-", f"{material_id}-{hashlib.sha256(data).hexdigest()[:16]}")[:128]
                ticket = client.request_upload(filename=filename, data_id=data_id, is_ocr=image_ocr)
                client.upload_bytes(ticket, data)
                batch_id = ticket.batch_id
                if on_event:
                    on_event("uploaded", {"batchId": batch_id, "traceId": ticket.trace_id, "ocrUsed": image_ocr})
            result = client.wait_for_result(
                batch_id,
                on_state=(lambda state: on_event("poll", {"batchId": batch_id, "state": state}) if on_event else None),
            )
            bundle_bytes = client.download_result(str(result["full_zip_url"]))
        parsed: MinerUBundle = read_mineru_bundle(bundle_bytes, image_ocr=image_ocr)
        quality = {"nativeCoverage": None, "fallbackPages": []}
        blocks = parsed.blocks
        if suffix in NATIVE_QUALITY_SUFFIXES:
            try:
                native = parse_native_document_blocks(data, filename=filename, content_type=content_type)
                blocks, quality = _apply_native_quality_gate(blocks, native)
            except DocumentParseError:
                quality["nativeGateUnavailable"] = True
        metadata = {
            **parsed.metadata,
            "batchId": batch_id,
            "ocrUsed": image_ocr,
            "modelVersion": settings.mineru_model_version,
            "qualityGate": quality,
        }
        if on_event:
            on_event("completed", metadata)
        return ParsedMaterial(
            blocks=blocks, provider="mineru-v4", bundle=bundle_bytes,
            markdown=parsed.markdown, metadata=metadata,
        )
    except MinerUError as exc:
        if on_event:
            on_event("failed", {"batchId": batch_id, "code": exc.code, "retryable": exc.retryable})
        if settings.mineru_enable_local_fallback:
            try:
                return _local_fallback(data, filename=filename, content_type=content_type, reason=exc.code)
            except DocumentParseError as fallback_exc:
                raise DocumentParseError(
                    f"MinerU failed ({exc.code}) and no usable local fallback result was produced"
                ) from fallback_exc
        raise DocumentParseError(f"MinerU parsing failed: {exc.code}") from exc
