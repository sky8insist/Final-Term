from typing import Literal

from pydantic import BaseModel, Field, model_validator

BlockType = Literal["paragraph", "heading", "table", "chart", "image", "formula", "audio"]


class ContentBlock(BaseModel):
    block_type: BlockType = Field(serialization_alias="blockType")
    content_text: str = Field(min_length=1, serialization_alias="contentText")
    structured_data: dict = Field(default_factory=dict, serialization_alias="structuredData")
    page_number: int | None = Field(default=None, ge=1, serialization_alias="pageNumber")
    bounding_box: dict | None = Field(default=None, serialization_alias="boundingBox")
    start_time: float | None = Field(default=None, ge=0, serialization_alias="startTime")
    end_time: float | None = Field(default=None, ge=0, serialization_alias="endTime")
    sequence_index: int = Field(ge=0, serialization_alias="sequenceIndex")
    parser_name: str = Field(serialization_alias="parserName")
    parser_version: str = Field(serialization_alias="parserVersion")
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_hash: str = Field(serialization_alias="sourceHash")
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.start_time is not None and self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("endTime must be greater than or equal to startTime")
        return self
