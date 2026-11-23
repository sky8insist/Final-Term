from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str
    user_id: str
    subject_id: str
    material_id: str
    chunk_index: int
    parent_chunk_id: str | None = None
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: str | None = None
