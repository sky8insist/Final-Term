from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal['material', 'notes', 'mind_map_node', 'wrong_answer']
TargetKind = Literal['notes', 'flashcards', 'mind_map', 'quiz', 'tutor']
CAPABILITIES = {'material': ['notes', 'flashcards', 'mind_map', 'quiz'],
                'notes': ['flashcards', 'mind_map', 'quiz', 'tutor'],
                'mind_map_node': ['flashcards', 'quiz', 'tutor'],
                'wrong_answer': ['tutor', 'notes', 'flashcards']}


class ConversionSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    kind: SourceKind
    id: UUID
    version: int | None = Field(default=None, ge=1)
    node_id: str | None = Field(default=None, alias='nodeId', min_length=1, max_length=100)
    block_ids: list[UUID] | None = Field(default=None,alias='blockIds',min_length=1,max_length=30)

    @model_validator(mode='after')
    def source_shape(self):
        if self.block_ids is not None and (self.kind!='material' or len(set(self.block_ids))!=len(self.block_ids)):
            raise ValueError('Only material sources accept unique blockIds')
        if (self.kind in {'notes', 'mind_map_node'}) != (self.version is not None):
            raise ValueError('Artifact sources require a version; other sources must omit it')
        if (self.kind == 'mind_map_node') != (self.node_id is not None):
            raise ValueError('Only mind_map_node sources require nodeId')
        return self


class ConversionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    request_id: UUID = Field(alias='requestId')
    subject_id: UUID = Field(alias='subjectId')
    source: ConversionSource
    target: TargetKind
    count: int = Field(default=10, ge=1, le=20)
    mode: Literal['summary', 'standard', 'comprehensive', 'exam_focus'] = 'standard'

    @model_validator(mode='after')
    def supported_pair(self):
        if self.target not in CAPABILITIES[self.source.kind]:
            raise ValueError('This source/target conversion is unsupported')
        return self
