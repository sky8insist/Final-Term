from typing import Literal

from pydantic import BaseModel, Field


class TomorrowItem(BaseModel):
    id: str
    source_item_id: str
    title: str
    next_action: str
    priority: Literal["high", "medium", "low"]
    blocked: bool
    blocker: str | None = None
    suggested_period: Literal["morning", "afternoon", "evening", "unspecified"]
    estimated_minutes: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)


class PlanningOutput(BaseModel):
    tomorrow_items: list[TomorrowItem] = Field(default_factory=list)
    deferred_items: list[str] = Field(default_factory=list)
    planning_summary: str
