import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import privacy_service

router = APIRouter()


@router.get("/export")
def export_data(current_user: CurrentUser = Depends(get_current_user)):
    payload = privacy_service.export_user_data(user_id=current_user.id)
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=examai-data-export.json"},
    )


@router.delete("/data")
def delete_data(confirm: str = Query(...), current_user: CurrentUser = Depends(get_current_user)):
    if confirm != "DELETE":
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Data deletion requires confirm=DELETE")
    return privacy_service.delete_learning_data(user_id=current_user.id)


@router.delete("/account")
def delete_account(confirm: str = Query(...), current_user: CurrentUser = Depends(get_current_user)):
    return privacy_service.delete_account(user_id=current_user.id, confirmation=confirm)
