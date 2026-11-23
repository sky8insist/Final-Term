from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from typing import Literal

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services.recommendation_service import next_actions
from app.services import product_analytics_service as analytics

def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/next-actions")
def recommendations(response: Response, subject_id: UUID | None = None, limit: int = Query(3, ge=1, le=10), audit: bool = False,
                     user: CurrentUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    result = next_actions(user_id=user.id, subject_id=str(subject_id) if subject_id else None, limit=limit)
    return analytics.deliver(user_id=user.id, result=result) if audit else result


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["impression", "clicked"]


@router.post("/{recommendation_id}/feedback")
def feedback(recommendation_id: UUID, payload: Feedback, user: CurrentUser = Depends(get_current_user)):
    return analytics.record_feedback(user_id=user.id, recommendation_id=str(recommendation_id), event=payload.event)


@router.get("/quality-metrics")
def quality_metrics(days: int = Query(7, ge=1, le=90), user: CurrentUser = Depends(get_current_user)):
    return analytics.metrics(user_id=user.id, days=days)


@router.get("/{recommendation_id}/audit")
def recommendation_audit(recommendation_id: UUID, cursor: str | None = Query(None, max_length=1024),
                         limit: int = Query(100, ge=1, le=100), user: CurrentUser = Depends(get_current_user)):
    return analytics.audit(user_id=user.id, recommendation_id=str(recommendation_id), cursor=cursor, limit=limit)


@router.get("/learning-outcomes")
def learning_outcomes(days: int = Query(30, ge=1, le=90), user: CurrentUser = Depends(get_current_user)):
    return analytics.learning_outcomes(user_id=user.id, days=days)


@router.get('/history')
def history(cursor: str | None = Query(None, max_length=1024), limit: int = Query(20, ge=1, le=100),
            user: CurrentUser = Depends(get_current_user)):
    return analytics.history(user_id=user.id, cursor=cursor, limit=limit)


@router.get('/prediction-coverage')
def prediction_coverage(days: int = Query(30, ge=1, le=90), user: CurrentUser = Depends(get_current_user)):
    return analytics.prediction_coverage(user_id=user.id, days=days)
