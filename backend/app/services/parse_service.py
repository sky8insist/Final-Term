from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

PDF_CONTENT_TYPE = "application/pdf"
TXT_CONTENT_TYPE = "text/plain"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentParseError(ValueError):
    pass


def _clean_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _parse_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("TXT file must be UTF-8 encoded") from exc


def _parse_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentParseError("PDF text could not be extracted") from exc

    return "\n".join(pages)


def _parse_docx(data: bytes) -> str:
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise DocumentParseError("DOCX text could not be extracted") from exc

    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def parse_document_bytes(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    suffix = Path(filename or "").suffix.lower()

    if content_type == TXT_CONTENT_TYPE or suffix == ".txt":
        text = _parse_txt(data)
    elif content_type == PDF_CONTENT_TYPE or suffix == ".pdf":
        text = _parse_pdf(data)
    elif content_type == DOCX_CONTENT_TYPE or suffix == ".docx":
        text = _parse_docx(data)
    else:
        raise DocumentParseError("Unsupported file type")

    cleaned = _clean_text(text)
    if not cleaned:
        raise DocumentParseError("No extractable text found in this file")

    return cleaned


def parse_document(path: str | Path) -> str:
    file_path = Path(path)
    return parse_document_bytes(file_path.read_bytes(), filename=file_path.name)
