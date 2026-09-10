from pydantic import BaseModel, Field


class EmotionReflection(BaseModel):
    events: list[str] = Field(default_factory=list)
    expressed_emotions: list[str] = Field(default_factory=list)
    unresolved_thoughts: list[str] = Field(default_factory=list)
    reflection_summary: str
    inferred_content: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
