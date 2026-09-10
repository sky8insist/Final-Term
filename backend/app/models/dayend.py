from typing import Any

from pydantic import BaseModel, Field


class DayendRunRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=8000, validation_alias="userInput")
    entry_point: str = Field(default="night", validation_alias="entryPoint")
    thread_id: str | None = Field(default=None, validation_alias="threadId")
    session_summary: str | None = Field(default=None, validation_alias="sessionSummary")


class DayendResumeRequest(BaseModel):
    response: dict[str, Any] = Field(default_factory=dict)
