from fastapi import HTTPException, UploadFile, status
from zipfile import BadZipFile, ZipFile

from app.config.settings import settings

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/jp2",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
}
EXTENSION_CONTENT_TYPES = {
    ".pdf": "application/pdf", ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".bmp": "image/bmp", ".jp2": "image/jp2",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/x-m4a",
}


def normalized_upload_content_type(file: UploadFile) -> str:
    declared = (file.content_type or "").lower()
    if declared in ALLOWED_CONTENT_TYPES:
        return declared
    filename = (file.filename or "").lower()
    extension = next((suffix for suffix in EXTENSION_CONTENT_TYPES if filename.endswith(suffix)), "")
    return EXTENSION_CONTENT_TYPES.get(extension, declared)


def get_upload_file_size(file: UploadFile) -> int:
    if file.size is not None:
        return file.size

    current_position = file.file.tell()
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(current_position)
    return size


def validate_upload_file(file: UploadFile) -> int:
    content_type = normalized_upload_content_type(file)
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    file_size = get_upload_file_size(file)
    if file_size <= 0:
        raise HTTPException(status_code=400, detail="File is empty")
    max_size = settings.max_upload_mb * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File must be {settings.max_upload_mb}MB or smaller",
        )

    position = file.file.tell()
    file.file.seek(0)
    head = file.file.read(min(file_size, 4096))
    file.file.seek(position)
    valid = True
    if content_type == "application/pdf":
        valid = head.startswith(b"%PDF-")
    elif content_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        try:
            file.file.seek(0)
            with ZipFile(file.file) as archive:
                marker = {
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word/document.xml",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt/presentation.xml",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xl/workbook.xml",
                }[content_type]
                valid = marker in archive.namelist()
        except (BadZipFile, OSError):
            valid = False
        finally:
            file.file.seek(position)
    elif content_type == "image/png":
        valid = head.startswith(b"\x89PNG\r\n\x1a\n")
    elif content_type == "image/jpeg":
        valid = head.startswith(b"\xff\xd8\xff")
    elif content_type == "image/webp":
        valid = len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    elif content_type == "image/gif":
        valid = head.startswith((b"GIF87a", b"GIF89a"))
    elif content_type == "image/bmp":
        valid = head.startswith(b"BM")
    elif content_type == "image/jp2":
        valid = head.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or head.startswith(b"\xff\x4f\xff\x51")
    elif content_type in {"application/msword", "application/vnd.ms-powerpoint", "application/vnd.ms-excel"}:
        valid = head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif content_type in {"audio/wav", "audio/x-wav"}:
        valid = len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    elif content_type == "audio/mpeg":
        valid = head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    elif content_type in {"audio/mp4", "audio/x-m4a"}:
        valid = len(head) >= 12 and head[4:8] == b"ftyp"
    elif content_type == "text/plain":
        valid = b"\x00" not in head
    if not valid:
        raise HTTPException(status_code=400, detail="File content does not match its declared type")
    return file_size
