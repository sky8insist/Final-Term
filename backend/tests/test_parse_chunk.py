from io import BytesIO

import pytest
from docx import Document

from app.services.chunk_service import build_chunk_records, chunk_text
from app.services.parse_service import (
    DOCX_CONTENT_TYPE,
    DocumentParseError,
    PDF_CONTENT_TYPE,
    TXT_CONTENT_TYPE,
    parse_document_bytes,
)


def test_parse_txt_supports_utf8_bom():
    text = parse_document_bytes(
        "\ufeff第一章\nmodule four".encode("utf-8"),
        filename="notes.txt",
        content_type=TXT_CONTENT_TYPE,
    )

    assert text == "第一章\nmodule four"


def test_parse_docx_extracts_paragraph_text():
    document = Document()
    document.add_paragraph("第一段")
    document.add_paragraph("second paragraph")
    buffer = BytesIO()
    document.save(buffer)

    text = parse_document_bytes(
        buffer.getvalue(),
        filename="notes.docx",
        content_type=DOCX_CONTENT_TYPE,
    )

    assert "第一段" in text
    assert "second paragraph" in text


def test_parse_pdf_uses_pypdf_extract_text(monkeypatch):
    class FakePage:
        def extract_text(self):
            return "pdf text"

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage()]

    monkeypatch.setattr("app.services.parse_service.PdfReader", FakeReader)

    text = parse_document_bytes(
        b"%PDF-1.4",
        filename="notes.pdf",
        content_type=PDF_CONTENT_TYPE,
    )

    assert text == "pdf text"


def test_parse_empty_pdf_fails(monkeypatch):
    class FakePage:
        def extract_text(self):
            return ""

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage()]

    monkeypatch.setattr("app.services.parse_service.PdfReader", FakeReader)

    with pytest.raises(DocumentParseError, match="No extractable text"):
        parse_document_bytes(
            b"%PDF-1.4",
            filename="notes.pdf",
            content_type=PDF_CONTENT_TYPE,
        )


def test_chunk_overlap_is_stable():
    chunks = chunk_text("abcdefghij", chunk_size=4, overlap=2)

    assert chunks == ["abcd", "cdef", "efgh", "ghij"]


def test_build_chunk_records_adds_metadata():
    records = build_chunk_records("abcdefghij", chunk_size=4, overlap=2)

    assert records[0]["chunk_index"] == 0
    assert records[0]["content"] == "abcd"
    assert records[0]["metadata"]["chunk_size"] == 4
    assert records[0]["metadata"]["overlap"] == 2
