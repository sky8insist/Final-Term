from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class OutlineRequest(BaseModel):
    subject_id: str
    scope: str | None = None


@router.post("/generate")
async def generate_outline(payload: OutlineRequest):
    return {"message": "outline endpoint", "subject_id": payload.subject_id}
