from typing import Literal

from pydantic import BaseModel

MaterialStatus = Literal["uploaded", "processing", "ready", "failed"]


class Material(BaseModel):
    id: str
    subject_id: str
    filename: str
    content_type: str
    file_size: int
    status: MaterialStatus
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
