from types import SimpleNamespace
from uuid import uuid4
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import ingestion_service, material_notes_service as service

USER, SUBJECT, MATERIAL, REQUEST, CONVERSION = [str(uuid4()) for _ in range(5)]


def material(**changes):
    return {'id': MATERIAL, 'user_id': USER, 'subject_id': SUBJECT, 'status': 'ready',
            'upload_notes_mode': 'standard', 'upload_notes_request_id': REQUEST,
            'upload_notes_dispatched': False, **changes}


@pytest.fixture
def authenticated():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=USER)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize('mode', [None, 'summary', 'standard', 'comprehensive', 'exam_focus'])
def test_upload_notes_mode_forwarding_and_default_off(authenticated, monkeypatch, mode):
    captured = {}
    monkeypatch.setattr(ingestion_service, 'queue_upload', lambda **kw: captured.update(kw) or {})
    data = {'subject_id': SUBJECT}
    if mode: data['notesMode'] = mode
    response = authenticated.post('/api/v1/materials/uploads', data=data,
                                  files={'file': ('notes.txt', b'notes', 'text/plain')})
    assert response.status_code == 202 and captured['notes_mode'] == mode
    assert captured['user_id'] == USER and captured['subject_id'] == SUBJECT


@pytest.mark.parametrize('mode', ['off', 'invalid', 'STANDARD'])
def test_invalid_notes_mode_does_not_upload(authenticated, monkeypatch, mode):
    monkeypatch.setattr(ingestion_service, 'queue_upload', lambda **_: pytest.fail('must not upload'))
    assert authenticated.post('/api/v1/materials/uploads', data={'subject_id': SUBJECT, 'notesMode': mode},
                              files={'file': ('notes.txt', b'notes', 'text/plain')}).status_code == 422


@pytest.mark.parametrize('changes', [
    {'upload_notes_mode': None}, {'status': 'parsing'}, {'upload_notes_dispatched': True},
])
def test_no_conversion_for_disabled_unready_or_already_dispatched(monkeypatch, changes):
    monkeypatch.setattr(service, '_owned', lambda **_: material(**changes))
    monkeypatch.setattr(service, 'transition', lambda *_: pytest.fail('must not claim'))
    assert service.enqueue_for_material(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL) is None


def test_upload_notes_uses_saved_request_and_existing_conversion_pipeline(monkeypatch):
    row = material(); transitions = []; payloads = []; dispatched = []
    monkeypatch.setattr(service, '_owned', lambda **_: row)
    def transition(*args):
        transitions.append(args)
        return row
    monkeypatch.setattr(service, 'transition', transition)
    monkeypatch.setattr(service.conversion_service, 'enqueue', lambda **kw: payloads.append(kw) or {'id': CONVERSION})
    monkeypatch.setattr(service.conversion_service, 'dispatch', lambda cid: dispatched.append(cid) or False)
    for _ in range(2):
        assert service.enqueue_for_material(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL)['id'] == CONVERSION
    assert payloads[0]['payload'].request_id == payloads[1]['payload'].request_id
    payload = payloads[0]['payload']
    assert str(payload.request_id) == REQUEST and str(payload.source.id) == MATERIAL
    assert payload.target == 'notes' and payload.mode == 'standard' and payload.count == 10
    assert transitions[1] == (USER, MATERIAL, 'done', CONVERSION)
    assert dispatched == [CONVERSION, CONVERSION]  # Broker failure uses conversion outbox, never a new request.


def test_concurrent_preparation_lease_skips_enqueue(monkeypatch):
    monkeypatch.setattr(service, '_owned', lambda **_: material())
    monkeypatch.setattr(service, 'transition', lambda *_: None)
    monkeypatch.setattr(service.conversion_service, 'enqueue', lambda **_: pytest.fail('lease unavailable'))
    assert service.enqueue_for_material(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL) is None


def test_preparation_error_is_recorded_without_broker_or_model_call(monkeypatch):
    row = material(); actions = []
    monkeypatch.setattr(service, '_owned', lambda **_: row)
    monkeypatch.setattr(service, 'transition', lambda *args: actions.append(args[2]) or row)
    def failure(**_): raise RuntimeError('private provider address')
    monkeypatch.setattr(service.conversion_service, 'enqueue', failure)
    monkeypatch.setattr(service.conversion_service, 'dispatch', lambda *_: pytest.fail('no job to dispatch'))
    with pytest.raises(RuntimeError): service.enqueue_for_material(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL)
    assert actions == ['start', 'error']


def test_sweep_continues_after_one_source_fails(monkeypatch):
    rows = [{'user_id': USER, 'subject_id': SUBJECT, 'id': 'broken'},
            {'user_id': USER, 'subject_id': SUBJECT, 'id': 'ready'}]
    monkeypatch.setattr(service, 'rpc', lambda *_: rows)
    visited = []
    def enqueue(**kw):
        visited.append(kw['material_id'])
        if kw['material_id'] == 'broken': raise RuntimeError('unavailable')
        return {'id': CONVERSION}
    monkeypatch.setattr(service, 'enqueue_for_material', enqueue)
    assert service.sweep() == 1 and visited == ['broken', 'ready']


def test_deleted_result_is_not_automatically_reenrolled(monkeypatch):
    monkeypatch.setattr(service, '_owned', lambda **_: material(upload_notes_dispatched=True))
    monkeypatch.setattr(service, 'existing', lambda _: None)
    monkeypatch.setattr(service, 'transition', lambda *_: pytest.fail('must preserve deletion'))
    with pytest.raises(HTTPException) as caught: service.retry(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL)
    assert caught.value.status_code == 409


def test_failed_generation_retry_uses_same_conversion(monkeypatch):
    monkeypatch.setattr(service, '_owned', lambda **_: material(upload_notes_dispatched=True))
    monkeypatch.setattr(service, 'existing', lambda _: CONVERSION)
    actions = []
    monkeypatch.setattr(service.conversion_service, 'transition', lambda **kw: actions.append(kw))
    monkeypatch.setattr(service.conversion_service, 'dispatch', lambda cid: actions.append(cid))
    assert service.retry(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL) == {'conversionId': CONVERSION}
    assert actions == [{'user_id': USER, 'conversion_id': CONVERSION, 'action': 'retry'}, CONVERSION]


def test_opt_out_cannot_be_retried(monkeypatch):
    monkeypatch.setattr(service, '_owned', lambda **_: material(upload_notes_mode=None))
    with pytest.raises(HTTPException) as caught: service.retry(user_id=USER, subject_id=SUBJECT, material_id=MATERIAL)
    assert caught.value.status_code == 409


@pytest.mark.parametrize('code,http', [('42501', 404), ('40001', 409), ('40P01', 409), ('22023', 422)])
def test_upload_notes_rpc_errors_are_sanitized(monkeypatch, code, http):
    class Failure(Exception): pass
    error = Failure('private database values'); error.code = code
    def rpc(*_): raise error
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(rpc=rpc))
    with pytest.raises(HTTPException) as caught: service.configure(user_id=USER, material_id=MATERIAL, mode='standard')
    assert caught.value.status_code == http and 'private database' not in caught.value.detail


def test_retry_api_passes_owner_scope(authenticated, monkeypatch):
    captured = {}
    monkeypatch.setattr(service, 'retry', lambda **kw: captured.update(kw) or {'conversionId': CONVERSION})
    assert authenticated.post(f'/api/v1/materials/{MATERIAL}/notes/retry?subject_id={SUBJECT}').status_code == 200
    assert captured == {'user_id': USER, 'subject_id': SUBJECT, 'material_id': MATERIAL}


@pytest.mark.parametrize('mode', [None, 'summary', 'standard', 'comprehensive', 'exam_focus'])
def test_upload_intent_is_persisted_in_material_insert(monkeypatch, mode):
    from app.services import material_service
    captured = {}
    class Query:
        def insert(self, values): captured.update(values); return self
        def select(self, *_): return self
        def execute(self): return SimpleNamespace(data=[{'id': MATERIAL, 'created_at': None, 'updated_at': None, **captured}])
    monkeypatch.setattr(material_service, 'get_supabase_client', lambda: SimpleNamespace(table=lambda _: Query()))
    row = material_service.create_queued_material(user_id=USER, subject_id=SUBJECT, filename='notes.txt',
        content_type='text/plain', file_size=5, source_hash='hash', upload_notes_mode=mode)
    assert row['uploadNotesMode'] == mode and captured['upload_notes_mode'] == mode
    assert captured['user_id'] == USER and captured['subject_id'] == SUBJECT
    if mode: assert UUID(captured['upload_notes_request_id'])
    else: assert captured['upload_notes_request_id'] is None


@pytest.mark.parametrize('mode,notes_fail', [(None, False), ('standard', False), ('standard', True)])
def test_worker_opt_in_and_optional_notes_failure(monkeypatch, mode, notes_fail):
    from app.services import material_ingestion_job_service as jobs, material_outline_service
    calls=[]
    monkeypatch.setattr(material_outline_service,'prepare',lambda **_: {})
    def enqueue(**kw):
        calls.append(kw)
        if notes_fail: raise RuntimeError('Notes temporarily unavailable')
        return {'id':CONVERSION}
    monkeypatch.setattr(service,'enqueue_for_material',enqueue)
    warnings=jobs.optional_postprocessing({'user_id':USER,'subject_id':SUBJECT,'material_id':MATERIAL}, {'upload_notes_mode':mode})
    assert len(calls)==(1 if mode else 0)
    assert ('notesWarning' in warnings) is notes_fail
