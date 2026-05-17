from fastapi import HTTPException, UploadFile, status

from app.config.settings import settings

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def get_upload_file_size(file: UploadFile) -> int:
    if file.size is not None:
        return file.size

    current_position = file.file.tell()
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(current_position)
    return size


def validate_upload_file(file: UploadFile) -> int:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    file_size = get_upload_file_size(file)
    max_size = settings.max_upload_mb * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File must be {settings.max_upload_mb}MB or smaller",
        )

    return file_size
