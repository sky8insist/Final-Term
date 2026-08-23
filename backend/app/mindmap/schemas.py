from typing import Literal

from pydantic import BaseModel, Field


NodeType = Literal[
    "root", "concept", "definition", "comparison", "process",
    "example", "exam_point", "warning",
]
ExamImportance = Literal["high", "medium", "low"]


class MindMapNode(BaseModel):
    id: str
    parent_id: str | None = Field(default=None, serialization_alias="parentId")
    label: str
    type: NodeType = "concept"
    level: int = Field(ge=0, le=4)
    importance: float = Field(default=0.5, ge=0, le=1)
    exam_importance: ExamImportance = Field(default="medium", serialization_alias="examImportance")
    mastery: float | None = Field(default=None, ge=0, le=1)
    description: str = ""
    source_ids: list[str] = Field(default_factory=list, serialization_alias="sourceIds")
    order: int = 0


class MindMapEdge(BaseModel):
    source: str
    target: str
    relation: str = "包含"


class MindMapEvaluation(BaseModel):
    relevance: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    hierarchy: float = Field(ge=0, le=1)
    grounding: float = Field(ge=0, le=1)
    redundancy: float = Field(ge=0, le=1)


class MindMapContent(BaseModel):
    title: str
    focus_question: str = Field(serialization_alias="focusQuestion")
    summary: str = ""
    mode: Literal["question", "topic", "chapter"]
    nodes: list[MindMapNode]
    edges: list[MindMapEdge]
    evaluation: MindMapEvaluation
    evidence_insufficient: bool = Field(default=False, serialization_alias="evidenceInsufficient")

