from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import ingestion_service, material_service, task_service
from app.worker import tasks

USER = '00000000-0000-0000-0000-000000000001'
SUBJECT = '00000000-0000-0000-0000-000000000010'


def task(**changes):
    return dict(id='task', user_id=USER, subject_id=SUBJECT, material_id='material',
                task_type='material_ingestion', status='failed', stage='failed', progress=45,
                attempts=3, max_attempts=3, metadata={}, **changes)


@pytest.fixture
def authenticated():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=USER)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize('route', ['upload', 'uploads'])
@pytest.mark.parametrize('purpose', ['learning', 'syllabus', 'reference'])
def test_upload_purpose_is_forwarded(authenticated, monkeypatch, route, purpose):
    captured = {}
    def upload(**kwargs):
        captured.update(kwargs)
        return {'id': 'material'}
    monkeypatch.setattr(material_service, 'create_uploaded_material', upload)
    monkeypatch.setattr(ingestion_service, 'queue_upload', upload)
    result = authenticated.post(f'/api/v1/materials/{route}', data={
        'subject_id': SUBJECT, 'materialPurpose': purpose,
    }, files={'file': ('notes.txt', b'notes', 'text/plain')})
    assert result.status_code in {200, 202}
    assert captured['user_id'] == USER and captured['subject_id'] == SUBJECT
    assert captured['material_purpose'] == purpose


@pytest.mark.parametrize('purpose', ['automatic-exams', 'SYLLABUS'])
def test_invalid_purpose_rejected_before_upload(authenticated, monkeypatch, purpose):
    monkeypatch.setattr(ingestion_service, 'queue_upload', lambda **_: pytest.fail('must not upload'))
    assert authenticated.post('/api/v1/materials/uploads', data={
        'subject_id': SUBJECT, 'materialPurpose': purpose,
    }, files={'file': ('notes.txt', b'notes', 'text/plain')}).status_code == 422


def test_summary_checks_subject_and_serializes_latest_task(monkeypatch):
    calls = []
    monkeypatch.setattr(ingestion_service, 'get_subject', lambda **kw: calls.append(kw))
    class Client:
        def rpc(self, name, args):
            assert name == 'material_processing_summary'
            assert args == {'p_user': USER, 'p_subject': SUBJECT}
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{
                'materialId': 'material', 'task': task(), 'sourceAvailable': True,
            }]))
    monkeypatch.setattr(ingestion_service, 'get_supabase_client', Client)
    row = ingestion_service.processing_summary(user_id=USER, subject_id=SUBJECT)[0]
    assert calls == [{'user_id': USER, 'subject_id': SUBJECT}]
    assert row['task']['materialId'] == 'material' and row['task']['maxAttempts'] == 3
    assert 'user_id' not in row['task'] and 'idempotency_key' not in row['task']


@pytest.mark.parametrize('code,http', [('42501', 404), ('22023', 409), ('40001', 409), ('23505', 409)])
def test_material_retry_maps_private_rpc_errors(monkeypatch, code, http):
    monkeypatch.setattr(task_service, 'get_task', lambda **_: {'taskType': 'material_ingestion'})
    class Failure(Exception):
        pass
    error = Failure('private database details'); error.code = code
    class Client:
        def rpc(self, name, args):
            assert name == 'retry_material_ingestion' and args['p_user'] == USER
            raise error
    monkeypatch.setattr(task_service, 'get_supabase_client', Client)
    with pytest.raises(HTTPException) as caught:
        task_service.retry_task(user_id=USER, task_id='task')
    assert caught.value.status_code == http
    assert 'private database' not in caught.value.detail


def test_dispatch_failure_is_persisted_without_exposing_broker_details(monkeypatch):
    def unavailable(*_): raise ConnectionError('secret broker address')
    monkeypatch.setattr(tasks.process_material, 'delay', unavailable)
    class Client:
        def rpc(self, name, args):
            assert name == 'fail_material_dispatch'
            assert args == {'p_user': USER, 'p_task': 'task'}
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=task()))
    monkeypatch.setattr(ingestion_service, 'get_supabase_client', Client)
    assert ingestion_service.dispatch_material(user_id=USER, task_id='task')['status'] == 'failed'


@pytest.mark.parametrize('existing_purpose,requested,expected', [
    ('syllabus', 'syllabus', True), ('syllabus', 'learning', False),
])
def test_dedup_precedes_quota_and_does_not_change_purpose(monkeypatch, existing_purpose, requested, expected):
    row = dict(id='material', subject_id=SUBJECT, filename='notes.txt', content_type='text/plain',
               file_size=5, status='ready', created_at=None, updated_at=None,
               material_purpose=existing_purpose)
    class Query:
        def select(self, *_): return self
        def eq(self, *_): return self
        def neq(self, *_): return self
        def limit(self, *_): return self
        def order(self, *_, **kw): return self
        def execute(self): return SimpleNamespace(data=self.rows)
    class Client:
        def table(self, name):
            query = Query(); query.rows = [row] if name == 'materials' else []
            return query
    monkeypatch.setattr(ingestion_service, 'get_subject', lambda **_: {})
    monkeypatch.setattr(ingestion_service, 'get_supabase_client', Client)
    file = UploadFile(BytesIO(b'notes'), filename='notes.txt', headers=Headers({'content-type': 'text/plain'}))
    if expected:
        result = ingestion_service.queue_upload(user_id=USER, subject_id=SUBJECT, file=file, material_purpose=requested)
        assert result['deduplicated'] and result['material']['materialPurpose'] == existing_purpose
    else:
        with pytest.raises(HTTPException) as caught:
            ingestion_service.queue_upload(user_id=USER, subject_id=SUBJECT, file=file, material_purpose=requested)
        assert caught.value.status_code == 409


@pytest.mark.parametrize('failure_stage', ['source', 'parsing', 'embedding', 'indexing'])
def test_worker_records_source_and_processing_failures(monkeypatch, failure_stage):
    from app.services import material_ingestion_job_service as jobs
    calls=[]
    job=task();job.update(status='running',ingestion_token='token')
    class Query:
        def select(self,*a):return self
        def eq(self,*a):return self
        def limit(self,*a):return self
        def execute(self):return SimpleNamespace(data=[{'user_id':USER}])
    monkeypatch.setattr(jobs,'get_supabase_client',lambda:SimpleNamespace(table=lambda _:Query()))
    def rpc(name,args):
        calls.append((name,args))
        return job if name=='claim_material_ingestion' else True
    monkeypatch.setattr(jobs,'rpc',rpc)
    error_type=type(failure_stage+'Failure',(RuntimeError,),{})
    def fail(*a):raise error_type('secret provider URL')
    monkeypatch.setattr(jobs,'execute',fail)
    assert tasks.process_material.run('task')['status']=='retry_or_failed'
    assert calls[-1]==('fail_material_ingestion',{'p_task':'task','p_token':'token','p_error':error_type.__name__})


def test_new_failed_upload_has_independent_storage_path():
    first = ingestion_service._object_path(USER, SUBJECT, 'hash', '../notes.txt', 'first')
    second = ingestion_service._object_path(USER, SUBJECT, 'hash', '../notes.txt', 'second')
    assert first != second and '../' not in first
