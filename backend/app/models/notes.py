from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NoteMode = Literal['summary', 'standard', 'comprehensive', 'exam_focus']


class NoteModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')


class NoteSection(NoteModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    citation_ids: list[UUID] = Field(alias='citationIds', min_length=1, max_length=100)


class NoteContent(NoteModel):
    sections: list[NoteSection] = Field(min_length=1, max_length=100)


class NoteGenerateRequest(NoteModel):
    subject_id: UUID = Field(alias='subjectId')
    mode: NoteMode = 'standard'
    scope: str | None = Field(default=None, max_length=1000)
    material_ids: list[UUID] | None = Field(default=None, alias='materialIds', max_length=100)
    knowledge_point_id: UUID | None = Field(default=None, alias='knowledgePointId')
    count: int = Field(default=12, ge=1, le=100)


class NoteUpdateRequest(NoteModel):
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    content: NoteContent


class NoteRestoreRequest(NoteModel):
    version: int = Field(ge=1)
    target_version: int = Field(alias='targetVersion', ge=1)


class NoteRewriteRequest(NoteModel):
    version: int = Field(ge=1)
    section_id: str = Field(alias='sectionId', min_length=1, max_length=100)
    selection_start: int = Field(alias='selectionStart', ge=0)
    selection_end: int = Field(alias='selectionEnd', ge=1)
    selected_text: str = Field(alias='selectedText', min_length=1, max_length=5000)
    instruction: str = Field(min_length=1, max_length=1000)


class NoteConvertRequest(NoteModel):
    version: int = Field(ge=1)
    target: Literal['flashcards', 'mind_map', 'quiz']
    count: int = Field(default=10, ge=1, le=20)
