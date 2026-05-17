from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import material_service

router = APIRouter()


@router.get("")
def list_materials(
    subject_id: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return material_service.list_materials(user_id=current_user.id, subject_id=subject_id)


@router.post("/upload")
def upload_material(
    subject_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    material = material_service.create_uploaded_material(
        user_id=current_user.id,
        subject_id=subject_id,
        file=file,
    )
    return {"material": material}
