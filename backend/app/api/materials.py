from fastapi import APIRouter, Depends, File, Form, UploadFile
from uuid import UUID

from app.api.deps import get_current_user
from app.models.user import CurrentUser
from app.models.material import MaterialPurpose
from app.models.material_outline import TopicProposalDecision
from app.models.notes import NoteMode
from app.services import content_service, ingestion_service, material_service

router = APIRouter()


@router.post('/{material_id}/notes/retry')
def retry_upload_notes(material_id: UUID, subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.material_notes_service import retry
    return retry(user_id=user.id, subject_id=str(subject_id), material_id=str(material_id))


@router.get('/{material_id}/outline')
def get_outline(material_id: UUID, subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.material_outline_service import get_outline
    return get_outline(user_id=user.id, subject_id=str(subject_id), material_id=str(material_id))


@router.post('/{material_id}/outline')
def prepare_outline(material_id: UUID, subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.material_outline_service import prepare
    return prepare(user_id=user.id, subject_id=str(subject_id), material_id=str(material_id))


@router.post('/topic-proposals/{proposal_id}/decision')
def decide_topic(proposal_id: UUID, payload: TopicProposalDecision, user: CurrentUser = Depends(get_current_user)):
    from app.services.material_outline_service import decide
    return decide(user_id=user.id, proposal_id=str(proposal_id), **payload.model_dump())


@router.get("")
def list_materials(
    subject_id: UUID | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return material_service.list_materials(
        user_id=current_user.id,
        subject_id=str(subject_id) if subject_id else None,
    )


@router.get("/{material_id}/blocks")
def list_material_blocks(
    material_id: str,
    block_type: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    return content_service.list_content_blocks(
        user_id=current_user.id, material_id=material_id, block_type=block_type,
    )


@router.get("/processing")
def material_processing(
    subject_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
):
    return ingestion_service.processing_summary(user_id=current_user.id, subject_id=str(subject_id))


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
    subject_id: UUID = Form(...),
    file: UploadFile = File(...),
    material_purpose: MaterialPurpose = Form("learning", alias="materialPurpose"),
    current_user: CurrentUser = Depends(get_current_user),
):
    material = material_service.create_uploaded_material(
        user_id=current_user.id,
        subject_id=str(subject_id),
        file=file,
        material_purpose=material_purpose,
    )
    return {"material": material}


@router.post("/uploads", status_code=202)
def queue_material_upload(
    subject_id: UUID = Form(...),
    file: UploadFile = File(...),
    material_purpose: MaterialPurpose = Form("learning", alias="materialPurpose"),
    notes_mode: NoteMode | None = Form(None, alias='notesMode'),
    current_user: CurrentUser = Depends(get_current_user),
):
    return ingestion_service.queue_upload(
        user_id=current_user.id, subject_id=str(subject_id), file=file, material_purpose=material_purpose,
        notes_mode=notes_mode,
    )
