from pydantic import BaseModel


class MorningFocus(BaseModel):
    title: str
    first_action: str
    source_item_id: str


class MorningBlockedItem(BaseModel):
    title: str
    blocker: str


class MorningOutput(BaseModel):
    opening: str
    primary_focus: MorningFocus | None = None
    secondary_items: list[str] = []
    blocked_items: list[MorningBlockedItem] = []
    emotion_handoff_available: bool = False
    emotion_handoff_message: str | None = None
