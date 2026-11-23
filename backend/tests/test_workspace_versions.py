import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import workspace_cache_service as service
from test_workspace_cache import FakeRedis

OWNER,SUBJECT=[str(UUID(int=i)) for i in range(1,3)]
A,B='a'*32,'b'*32


@pytest.fixture
def cache(monkeypatch):
    fake=FakeRedis();monkeypatch.setattr(service,'get_redis_client',lambda:fake)
    monkeypatch.setattr(service,'current_version',lambda **_:{'version':A})
    return fake


def test_old_snapshot_inaccessible_after_version_change(cache,monkeypatch):
    service.save_snapshot(user_id=OWNER,resource='dashboard',data={'mastery':.2},expected_version=A)
    monkeypatch.setattr(service,'current_version',lambda **_:{'version':B})
    assert service.load_snapshot(user_id=OWNER,resource='dashboard') is None
    with pytest.raises(HTTPException) as error:service.save_snapshot(user_id=OWNER,resource='dashboard',data={},expected_version=A)
    assert error.value.status_code==409 and len(cache.values)==1


def test_concurrent_change_after_redis_read_cannot_return_old_data(cache,monkeypatch):
    service.save_snapshot(user_id=OWNER,resource='dashboard',data={},expected_version=A)
    values=iter([A,B])
    monkeypatch.setattr(service,'current_version',lambda **_:{'version':next(values)})
    assert service.load_snapshot(user_id=OWNER,resource='dashboard') is None


@pytest.mark.parametrize('payload',['[]','null','123','{bad}',json.dumps({'schemaVersion':1}),json.dumps({'schemaVersion':2,'version':B})])
def test_corrupt_or_legacy_envelopes_are_rejected(cache,payload):
    cache.setex(service._key(user_id=OWNER,resource='dashboard',subject_id=None,version=A),300,payload)
    assert service.load_snapshot(user_id=OWNER,resource='dashboard') is None


def test_failed_version_validation_never_reads_redis(cache,monkeypatch):
    def unavailable(**_):raise RuntimeError('Version unavailable')
    monkeypatch.setattr(service,'current_version',unavailable)
    monkeypatch.setattr(cache,'get',lambda *_:pytest.fail('Unvalidated Redis read'))
    with pytest.raises(RuntimeError):service.load_snapshot(user_id=OWNER,resource='dashboard')


def test_old_writer_cannot_overwrite_current_version_key(cache,monkeypatch):
    service.save_snapshot(user_id=OWNER,resource='dashboard',data={'new':False},expected_version=A)
    monkeypatch.setattr(service,'current_version',lambda **_:{'version':B})
    service.save_snapshot(user_id=OWNER,resource='dashboard',data={'new':True},expected_version=B)
    assert service.load_snapshot(user_id=OWNER,resource='dashboard')['data']=={'new':True}
    assert len(cache.values)==2


@pytest.mark.parametrize('code,status',[('42501',404),('22023',422),('22P02',422),('unavailable',503)])
def test_version_api_errors_and_identity(monkeypatch,code,status):
    calls=[]
    class Failure(Exception):pass
    exc=Failure('private');exc.code=code
    def rpc(name,values):calls.append(values);raise exc
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace(rpc=rpc))
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            result=client.get('/api/v1/workspace/cache/chat/version',params={'subjectId':SUBJECT})
            assert result.status_code==status and 'private' not in result.text
            assert calls==[{'p_user':OWNER,'p_resource':'chat','p_subject':SUBJECT}]
    finally:app.dependency_overrides.pop(get_current_user,None)


@pytest.mark.parametrize('body',[{'data':{}},{'data':{},'expectedVersion':'bad'},{'data':{},'expectedVersion':A,'subjectId':'foreign'},
    {'data':{},'expectedVersion':A,'user_id':OWNER}])
def test_cache_put_requires_version_and_valid_scope_shape(body):
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:assert client.put('/api/v1/workspace/cache/dashboard',json=body).status_code==422
    finally:app.dependency_overrides.pop(get_current_user,None)


def test_nonfinite_cache_payload_cannot_be_saved(cache):
    with pytest.raises(ValueError):service.save_snapshot(user_id=OWNER,resource='dashboard',data={'value':float('nan')},expected_version=A)
    assert not cache.values


def test_privacy_reset_revokes_database_generation_even_when_redis_is_down(monkeypatch):
    from redis.exceptions import ConnectionError
    calls=[]
    def rpc(name,values):calls.append((name,values));return SimpleNamespace(execute=lambda:None)
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace(rpc=rpc))
    def fail():raise ConnectionError('Offline')
    monkeypatch.setattr(service,'get_redis_client',fail)
    service.reset_user_snapshots(user_id=OWNER)
    assert calls==[('revoke_workspace_snapshots',{'p_user':OWNER})]
