from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import retrieval_service

router = APIRouter()


class RetrievalSearchRequest(BaseModel):
    subject_id: str = Field(validation_alias="subjectId")
    question: str
    top_k: int | None = Field(default=None, validation_alias="topK")
    material_ids: list[str] | None = Field(default=None, validation_alias="materialIds")
    block_types: list[str] | None = Field(default=None, validation_alias="blockTypes")
    page_from: int | None = Field(default=None, ge=1, validation_alias="pageFrom")
    page_to: int | None = Field(default=None, ge=1, validation_alias="pageTo")
    start_time: float | None = Field(default=None, ge=0, validation_alias="startTime")
    end_time: float | None = Field(default=None, ge=0, validation_alias="endTime")
    min_confidence: float | None = Field(default=None, ge=0, le=1, validation_alias="minConfidence")


@router.post("/search")
def search_retrieval_context(
    payload: RetrievalSearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return retrieval_service.search_subject_context(
        user_id=current_user.id,
        subject_id=payload.subject_id,
        question=payload.question,
        top_k=payload.top_k,
        material_ids=payload.material_ids,
        block_types=payload.block_types,
        page_from=payload.page_from,
        page_to=payload.page_to,
        start_time=payload.start_time,
        end_time=payload.end_time,
        min_confidence=payload.min_confidence,
    )
