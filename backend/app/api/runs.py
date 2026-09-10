import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.models.dayend import DayendResumeRequest, DayendRunRequest
from app.models.user import CurrentUser
from app.services.dayend_run_service import create_run, get_run, resume_run, stream_run

router = APIRouter()


@router.post("/runs")
async def create_dayend_run(payload: DayendRunRequest, current_user: CurrentUser = Depends(get_current_user)):
    return await create_run(request=payload, user_id=current_user.id)


@router.get("/runs/{thread_id}")
async def get_dayend_run(thread_id: str, _: CurrentUser = Depends(get_current_user)):
    return await get_run(thread_id=thread_id)


@router.post("/runs/{thread_id}/resume")
async def resume_dayend_run(thread_id: str, payload: DayendResumeRequest, _: CurrentUser = Depends(get_current_user)):
    return await resume_run(thread_id=thread_id, response=payload.response)


@router.post("/runs/stream")
async def stream_dayend_run(payload: DayendRunRequest, current_user: CurrentUser = Depends(get_current_user)):
    async def events():
        async for item in stream_run(request=payload, user_id=current_user.id):
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")
