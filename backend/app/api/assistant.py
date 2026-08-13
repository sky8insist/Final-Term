from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.assistant import AssistantMessageRequest
from app.models.user import CurrentUser
from app.services.assistant_service import handle_message

router = APIRouter()


@router.post("/messages")
async def send_message(
    payload: AssistantMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await handle_message(user_id=current_user.id, payload=payload)
