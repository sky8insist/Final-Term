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
    )
