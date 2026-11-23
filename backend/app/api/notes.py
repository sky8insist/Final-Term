from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.notes import NoteConvertRequest, NoteGenerateRequest, NoteRestoreRequest, NoteRewriteRequest, NoteUpdateRequest
from app.models.user import CurrentUser
from app.services import notes_service

router = APIRouter()


@router.get('')
def list_notes(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return notes_service.list_notes(user_id=user.id, subject_id=str(subject_id))


@router.post('')
async def generate_note(payload: NoteGenerateRequest, user: CurrentUser = Depends(get_current_user)):
    return await notes_service.generate_note(user_id=user.id, payload=payload)


@router.get('/{note_id}')
def get_note(note_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return notes_service.get_note(user_id=user.id, note_id=str(note_id))


@router.patch('/{note_id}')
def update_note(note_id: UUID, payload: NoteUpdateRequest, user: CurrentUser = Depends(get_current_user)):
    return notes_service.update_note(user_id=user.id, note_id=str(note_id), version=payload.version,
        title=payload.title, content=payload.content.model_dump(mode='json', by_alias=True))


@router.get('/{note_id}/versions')
def versions(note_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return notes_service.versions(user_id=user.id, note_id=str(note_id))


@router.post('/{note_id}/restore')
def restore(note_id: UUID, payload: NoteRestoreRequest, user: CurrentUser = Depends(get_current_user)):
    return notes_service.restore(user_id=user.id, note_id=str(note_id), version=payload.version, target_version=payload.target_version)


@router.get('/{note_id}/versions/{version}')
def get_version(note_id: UUID, version: int, user: CurrentUser = Depends(get_current_user)):
    return notes_service.get_version(user_id=user.id, note_id=str(note_id), version=version)


@router.post('/{note_id}/rewrite')
async def rewrite(note_id: UUID, payload: NoteRewriteRequest, user: CurrentUser = Depends(get_current_user)):
    return await notes_service.rewrite(user_id=user.id, note_id=str(note_id), payload=payload)


@router.post('/{note_id}/convert', deprecated=True)
async def convert(note_id: UUID, payload: NoteConvertRequest, user: CurrentUser = Depends(get_current_user)):
    return await notes_service.convert(user_id=user.id, note_id=str(note_id), payload=payload)
