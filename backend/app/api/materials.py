from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.services import content_service, ingestion_service, material_service

router = APIRouter()


@router.get("")
def list_materials(
    subject_id: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return material_service.list_materials(user_id=current_user.id, subject_id=subject_id)


@router.get("/{material_id}/blocks")
def list_material_blocks(
    material_id: str,
    block_type: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return content_service.list_content_blocks(
        user_id=current_user.id, material_id=material_id, block_type=block_type,
    )


@router.get("/{material_id}/source")
def get_material_source(
    material_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return material_service.get_material_source(
        user_id=current_user.id, material_id=material_id,
    )


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


@router.post("/uploads", status_code=202)
def queue_material_upload(
    subject_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    return ingestion_service.queue_upload(
        user_id=current_user.id, subject_id=subject_id, file=file,
    )
