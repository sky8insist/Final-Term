from typing import Literal

from pydantic import BaseModel, Field


class ClosureItem(BaseModel):
    id: str
    content: str = Field(min_length=1)
    category: Literal["completed", "unfinished", "waiting", "uncertain"]
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    user_commitment: bool


class ClosureOutput(BaseModel):
    items: list[ClosureItem] = Field(default_factory=list)
    overall_summary: str
    needs_confirmation_ids: list[str] = Field(default_factory=list)
