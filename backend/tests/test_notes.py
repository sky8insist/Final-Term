import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.notes import NoteConvertRequest, NoteGenerateRequest, NoteRewriteRequest
from app.models.user import CurrentUser
from app.services import artifact_service, notes_service

OWNER, SUBJECT, NOTE, BLOCK, OTHER = [str(UUID(int=index)) for index in range(1, 6)]
CONTENT = {'sections': [{'id': 's1', 'title': 'Definition', 'body': 'A😀B definition', 'citationIds': [BLOCK]}]}
CITATIONS = [{'id': BLOCK, 'materialId': OTHER, 'filename': 'source.pdf', 'pageNumber': 7, 'chunkText': 'Canonical evidence', 'startTime': None}]


def note():
    return {'id': NOTE, 'subject_id': SUBJECT, 'artifact_type': 'notes', 'version': 1, 'title': 'Notes',
            'content': deepcopy(CONTENT), 'citations': deepcopy(CITATIONS), 'generation_params': {'mode': 'standard', 'knowledgePointIds': []}}


@pytest.fixture
def scoped(monkeypatch):
    calls = []
    class Client:
        def rpc(self, name, params):
            calls.append((name, deepcopy(params)))
            assert params['p_user_id'] == OWNER and params['p_subject_id'] == SUBJECT
            if name == 'note_source_citations':
                data = deepcopy(CITATIONS)
            else:
                data = {**note(), 'version': (params['p_expected_version'] or 0) + 1,
                        'title': params['p_values']['title'], 'content': params['p_values']['content']}
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))
    monkeypatch.setattr(notes_service, 'get_supabase_client', lambda: Client())
    monkeypatch.setattr(notes_service, 'get_subject', lambda **_: None)
    monkeypatch.setattr(notes_service, 'get_note', lambda **_: note())
    monkeypatch.setattr(notes_service, 'search_subject_context', lambda **_: {'citations': deepcopy(CITATIONS)})
    return calls


@pytest.mark.parametrize('mode', ['summary', 'standard', 'comprehensive', 'exam_focus'])
def test_generate_modes_use_canonical_sources_and_private_atomic_save(scoped, monkeypatch, mode):
    prompts = []
    async def model(prompt):
        prompts.append(prompt)
        return {'title': 'Generated', **deepcopy(CONTENT)}
    monkeypatch.setattr(notes_service, 'generate_json_async', model)
    result = asyncio.run(notes_service.generate_note(user_id=OWNER, payload=NoteGenerateRequest(subjectId=SUBJECT, mode=mode)))
    assert result['version'] == 1
    assert notes_service.MODES[mode] in prompts[0] and 'Canonical evidence' in prompts[0]
    assert scoped[-1][0] == 'save_note' and scoped[-1][1]['p_values']['mode'] == mode
    assert scoped[-1][1]['p_values']['citationIds'] == [BLOCK]


def test_generation_repairs_unknown_citation_before_any_write(scoped, monkeypatch):
    attempts = []
    async def model(prompt):
        attempts.append(prompt)
        content = deepcopy(CONTENT)
        if len(attempts) == 1:
            content['sections'][0]['citationIds'] = [OTHER]
        return {'title': 'Generated', **content}
    monkeypatch.setattr(notes_service, 'generate_json_async', model)
    asyncio.run(notes_service.generate_note(user_id=OWNER, payload=NoteGenerateRequest(subjectId=SUBJECT)))
    assert len(attempts) == 2
    assert sum(name == 'save_note' for name, _ in scoped) == 1


def test_invalid_model_output_never_writes(scoped, monkeypatch):
    async def model(_): return {'title': 'Wrong', 'sections': []}
    monkeypatch.setattr(notes_service, 'generate_json_async', model)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(notes_service.generate_note(user_id=OWNER, payload=NoteGenerateRequest(subjectId=SUBJECT)))
    assert failure.value.status_code == 502
    assert not any(name == 'save_note' for name, _ in scoped)


@pytest.mark.parametrize('bad', [
    {'sections': []},
    {'sections': [{**CONTENT['sections'][0], 'body': ' '} ]},
    {'sections': [{**CONTENT['sections'][0], 'citationIds': []}]},
    {'sections': [{**CONTENT['sections'][0], 'citationIds': [OTHER]}]},
    {'sections': [CONTENT['sections'][0], CONTENT['sections'][0]]},
    {'sections': [{**CONTENT['sections'][0], 'uncitedFact': 'invented'}]},
])
def test_editor_rejects_invalid_content(bad):
    with pytest.raises(HTTPException) as failure:
        notes_service.validate_content(bad, {BLOCK})
    assert failure.value.status_code == 422


def test_unavailable_canonical_source_is_rejected(monkeypatch):
    monkeypatch.setattr(notes_service, 'get_supabase_client', lambda: SimpleNamespace(rpc=lambda *_: SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))))
    with pytest.raises(HTTPException) as failure:
        notes_service.canonical_sources(user_id=OWNER, subject_id=SUBJECT, block_ids=[BLOCK])
    assert failure.value.status_code == 422


def test_note_update_uses_expected_version_and_preserves_bindings(scoped):
    result = notes_service.update_note(user_id=OWNER, note_id=NOTE, version=1, title='Edited', content=CONTENT)
    assert result['version'] == 2
    params = scoped[-1][1]
    assert params['p_expected_version'] == 1 and params['p_note_id'] == NOTE
    assert params['p_values']['citationIds'] == [BLOCK]


def test_save_drops_unused_source_links(scoped):
    notes_service._save(user_id=OWNER, subject_id=SUBJECT, note_id=NOTE, version=1, title='Notes', content=CONTENT,
        citations=[*CITATIONS, {**CITATIONS[0], 'id': OTHER}], topic_ids=[], mode='standard', params={})
    assert scoped[-1][1]['p_values']['citationIds'] == [BLOCK]


def test_restore_reads_owned_snapshot_and_appends_new_version(monkeypatch):
    filters, saved = {}, []
    original = {**note(), 'title': 'Historical title'}
    current = {**note(), 'version': 3, 'title': 'Current title'}
    class Query:
        def select(self, *_): return self
        def eq(self, key, value): filters[key] = value; return self
        def limit(self, *_): return self
        def execute(self): return SimpleNamespace(data=[{'snapshot': deepcopy(original)}])
    monkeypatch.setattr(notes_service, 'get_note', lambda **_: current)
    monkeypatch.setattr(notes_service, 'get_supabase_client', lambda: SimpleNamespace(table=lambda _: Query()))
    monkeypatch.setattr(notes_service, '_save', lambda **kwargs: saved.append(kwargs) or {'version': 4})
    result = notes_service.restore(user_id=OWNER, note_id=NOTE, version=3, target_version=1)
    assert filters == {'user_id': OWNER, 'artifact_id': NOTE, 'version': 1}
    assert result['version'] == 4 and saved[0]['version'] == 3
    assert saved[0]['title'] == 'Historical title' and saved[0]['params']['restoredFromVersion'] == 1
    assert original['title'] == 'Historical title'


@pytest.mark.parametrize('code,status', [('40001', 409), ('40P01', 409), ('42501', 404), ('22023', 422), ('23503', 422)])
def test_database_errors_are_recoverable_not_silent(monkeypatch, code, status):
    class Error(Exception): pass
    failure = Error('database rejection'); failure.code = code
    def fail(): raise failure
    monkeypatch.setattr(notes_service, 'get_supabase_client', lambda: SimpleNamespace(rpc=lambda *_: SimpleNamespace(execute=fail)))
    with pytest.raises(HTTPException) as actual:
        notes_service._save(user_id=OWNER, subject_id=SUBJECT, note_id=NOTE, version=1, title='Notes', content=CONTENT,
            citations=CITATIONS, topic_ids=[], mode='standard', params={})
    assert actual.value.status_code == status


def rewrite_request(**extra):
    return NoteRewriteRequest(**{'version': 1, 'sectionId': 's1', 'selectionStart': 1,
        'selectionEnd': 2, 'selectedText': '😀', 'instruction': 'Explain clearly', **extra})


def test_unicode_rewrite_is_preview_only(scoped, monkeypatch):
    async def model(_): return {'replacement': 'symbol', 'citationIds': [BLOCK]}
    monkeypatch.setattr(notes_service, 'generate_json_async', model)
    result = asyncio.run(notes_service.rewrite(user_id=OWNER, note_id=NOTE, payload=rewrite_request()))
    assert result['replacement'] == 'symbol' and result['selectionEnd'] == 2
    assert not any(name == 'save_note' for name, _ in scoped)
    assert note()['content'] == CONTENT


@pytest.mark.parametrize('extra', [{'version': 2}, {'selectedText': 'wrong'}, {'selectionEnd': 999}, {'sectionId': 'unknown'}])
def test_rewrite_rejects_stale_or_mismatched_selection_before_model(scoped, extra):
    with pytest.raises(HTTPException) as failure:
        asyncio.run(notes_service.rewrite(user_id=OWNER, note_id=NOTE, payload=rewrite_request(**extra)))
    assert failure.value.status_code == 409 and scoped == []


def test_rewrite_rejects_invented_sources(scoped, monkeypatch):
    async def model(_): return {'replacement': 'invented', 'citationIds': [OTHER]}
    monkeypatch.setattr(notes_service, 'generate_json_async', model)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(notes_service.rewrite(user_id=OWNER, note_id=NOTE, payload=rewrite_request()))
    assert failure.value.status_code == 502


def test_rewrite_detects_changes_during_model_call(scoped, monkeypatch):
    states = iter([note(), {**note(), 'version': 2}])
    monkeypatch.setattr(notes_service, 'get_note', lambda **_: next(states))
    async def model(_): return {'replacement': 'symbol', 'citationIds': [BLOCK]}
    monkeypatch.setattr(notes_service, 'generate_json_async', model)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(notes_service.rewrite(user_id=OWNER, note_id=NOTE, payload=rewrite_request()))
    assert failure.value.status_code == 409


@pytest.mark.parametrize('target', ['flashcards', 'mind_map', 'quiz'])
def test_conversion_uses_saved_version_and_original_sources(scoped, monkeypatch, target):
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return {'id': OTHER, 'title': 'Converted'}
    from app.services import exam_service
    monkeypatch.setattr(artifact_service, 'generate_artifact', generate)
    monkeypatch.setattr(exam_service, 'generate_exam', generate)
    result = asyncio.run(notes_service.convert(user_id=OWNER, note_id=NOTE, payload=NoteConvertRequest(version=1, target=target)))
    context = calls[0]['source_context']
    assert result['sourceArtifactId'] == NOTE and result['sourceArtifactVersion'] == 1
    assert context['noteContent'] == CONTENT and context['citations'][0]['id'] == BLOCK
    assert context['retrieval']['externalUsed'] is False
    if target == 'quiz':
        assert calls[0]['payload'].knowledge_policy == 'course_only'
    assert not any(name == 'save_note' for name, _ in scoped)


def test_conversion_rejects_stale_version(scoped):
    with pytest.raises(HTTPException) as failure:
        asyncio.run(notes_service.convert(user_id=OWNER, note_id=NOTE, payload=NoteConvertRequest(version=2, target='quiz')))
    assert failure.value.status_code == 409 and scoped == []


def test_notes_markdown_has_body_and_source_location(monkeypatch):
    monkeypatch.setattr(artifact_service, 'get_artifact', lambda **_: note())
    data, media, _ = artifact_service.export_artifact(user_id=OWNER, artifact_id=NOTE, export_format='markdown')
    text = data.decode('utf-8')
    assert 'A😀B definition' in text and 'source.pdf' in text and '第 7 页' in text and BLOCK in text
    assert media.startswith('text/markdown')
    with pytest.raises(HTTPException) as failure:
        artifact_service.export_artifact(user_id=OWNER, artifact_id=NOTE, export_format='png')
    assert failure.value.status_code == 400


def test_generic_artifact_patch_cannot_bypass_notes_version(monkeypatch):
    monkeypatch.setattr(artifact_service, 'get_artifact', lambda **_: note())
    with pytest.raises(HTTPException) as failure:
        artifact_service.update_artifact(user_id=OWNER, artifact_id=NOTE, title='Edit', content=CONTENT)
    assert failure.value.status_code == 422


@pytest.mark.parametrize('method,path', [('GET', ''), ('POST', ''), ('GET', f'/{NOTE}'), ('PATCH', f'/{NOTE}'),
    ('GET', f'/{NOTE}/versions'), ('GET', f'/{NOTE}/versions/1'), ('POST', f'/{NOTE}/restore'),
    ('POST', f'/{NOTE}/rewrite'), ('POST', f'/{NOTE}/convert')])
def test_notes_routes_require_login(method, path):
    assert TestClient(app).request(method, '/api/v1/notes' + path).status_code == 401


def test_api_patch_requires_version_and_valid_citations(scoped):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=OWNER, email=None)
    try:
        client = TestClient(app)
        assert client.patch(f'/api/v1/notes/{NOTE}', json={'title': 'Edit', 'content': CONTENT}).status_code == 422
        response = client.patch(f'/api/v1/notes/{NOTE}', json={'version': 1, 'title': 'Edit', 'content': CONTENT})
        assert response.status_code == 200 and response.json()['version'] == 2
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(previous)
