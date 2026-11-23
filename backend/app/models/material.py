from typing import Literal

from pydantic import BaseModel

MaterialStatus = Literal["uploaded", "queued", "processing", "parsing", "embedding", "indexing", "ready", "failed"]
MaterialPurpose = Literal["learning", "syllabus", "reference"]


class Material(BaseModel):
    id: str
    subject_id: str
    filename: str
    content_type: str
    file_size: int
    status: MaterialStatus
    material_purpose: MaterialPurpose = "learning"
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
