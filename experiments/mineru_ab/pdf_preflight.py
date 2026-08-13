from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(frozen=True)
class PdfPreflight:
    accepted: bool
    page_count: int
    sampled_pages: int
    extracted_characters: int
    pages_with_text: int
    reason: str | None = None


def inspect_pdf_text_layer(
    path: Path, *, sample_pages: int = 5, min_text_chars_per_page: int = 20,
) -> PdfPreflight:
    try:
        document = fitz.open(path)
    except Exception as exc:
        return PdfPreflight(False, 0, 0, 0, 0, f"invalid_pdf:{type(exc).__name__}")
    try:
        if document.needs_pass:
            return PdfPreflight(False, document.page_count, 0, 0, 0, "encrypted_pdf")
        count = min(document.page_count, max(sample_pages, 1))
        text_lengths = [len(document[index].get_text("text").strip()) for index in range(count)]
        total = sum(text_lengths)
        pages_with_text = sum(length >= min_text_chars_per_page for length in text_lengths)
        accepted = count > 0 and pages_with_text > 0
        return PdfPreflight(
            accepted, document.page_count, count, total, pages_with_text,
            None if accepted else "ocr_required",
        )
    finally:
        document.close()

