from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TopicProposalDecision(BaseModel):
    version: int = Field(ge=1)
    action: Literal['accept', 'reject']
    title: str | None = Field(default=None, max_length=300)

    @field_validator('title')
    @classmethod
    def clean_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError('知识点名称不能为空')
        return value.strip() if value is not None else None
