from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import CurrentUser

router = APIRouter()


@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return current_user
