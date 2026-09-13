from typing import Literal

from pydantic import BaseModel, Field, model_validator


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

    @model_validator(mode="after")
    def validate_confirmation_items(self):
        """Make uncertain closure facts explicitly reviewable by the user."""
        item_ids = {item.id for item in self.items}
        unknown_ids = set(self.needs_confirmation_ids) - item_ids
        if unknown_ids:
            raise ValueError("needs_confirmation_ids must reference extracted closure items")
        uncertain_ids = {item.id for item in self.items if item.category == "uncertain"}
        missing_ids = uncertain_ids - set(self.needs_confirmation_ids)
        if missing_ids:
            raise ValueError("uncertain closure items must require human confirmation")
        return self
