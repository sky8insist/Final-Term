from types import SimpleNamespace as NS
from uuid import UUID

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from supabase_auth.errors import AuthApiError

from app.api import deps
from app.config.settings import settings
from app.services import privacy_service as service

OWNER = str(UUID(int=1))


def test_export_does_not_hide_failed_tables(monkeypatch):
    def fail(*args):
        raise RuntimeError('private database details')
    monkeypatch.setattr(service, 'get_supabase_client', lambda: NS(rpc=fail))
    with pytest.raises(HTTPException) as error:
        service.export_user_data(user_id=OWNER)
    assert error.value.status_code == 503
    assert 'private' not in str(error.value.detail)


def test_export_preserves_rpc_bundle_without_truncating(monkeypatch):
    bundle = {'data': {'product_events': [{'id': i} for i in range(1005)]}}
    monkeypatch.setattr(service, 'get_supabase_client', lambda: NS(rpc=lambda *a: NS(execute=lambda: NS(data=bundle))))
    assert len(service.export_user_data(user_id=OWNER)['data']['product_events']) == 1005


def test_cleanup_reads_until_empty_despite_server_cap():
    rows = [{'id': n} for n in range(205)]
    class Query:
        def select(self, *a): return self
        def eq(self, key, value):
            assert (key, value) == ('user_id', OWNER)
            return self
        def order(self, *a): return self
        def range(self, start, end): self.start = start; return self
        def execute(self): return NS(data=rows[self.start:self.start+17])
    assert service._owned_rows(NS(table=lambda _: Query()), 'material_assets', OWNER) == rows


@pytest.mark.parametrize('phase', ['storage', 'index', 'metadata'])
def test_external_failure_retains_relational_records(monkeypatch, phase):
    calls = []
    index = [{'material_id': 'm'}] if phase != 'storage' else []
    chunks = [{'material_id': 'm', 'subject_id': 's', 'embedding_dimensions': 4}] if phase == 'index' else []
    def owned(client, table, user_id, columns='*'):
        return {'lightrag_material_index': index, 'material_chunks': chunks,
                'material_assets': [{'bucket': 'study-materials', 'object_path': 'file'}]}.get(table, [])
    def fail(*a, **kw): raise service.LightRAGServiceError('private')
    monkeypatch.setattr(service, '_owned_rows', owned)
    monkeypatch.setattr(service, 'delete_material_index', fail)
    fake = NS(rpc=lambda *a: calls.append(a), storage=NS(from_=lambda _: NS(remove=fail)))
    monkeypatch.setattr(service, 'get_supabase_client', lambda: fake)
    with pytest.raises(HTTPException) as error: service.delete_learning_data(user_id=OWNER)
    assert error.value.status_code == 502 and not calls


def test_auth_deletion_failure_can_retry_after_learning_clear(monkeypatch):
    calls = []
    monkeypatch.setattr(service, 'delete_learning_data', lambda **kw: calls.append('clear'))
    def fail(*a): raise RuntimeError('secret')
    fake = NS(auth=NS(admin=NS(delete_user=fail)))
    monkeypatch.setattr(service, 'get_supabase_client', lambda: fake)
    with pytest.raises(HTTPException) as error: service.delete_account(user_id=OWNER, confirmation='DELETE')
    assert error.value.status_code == 502 and 'secret' not in str(error.value.detail)
    fake.auth.admin.delete_user = lambda _: calls.append('auth')
    assert service.delete_account(user_id=OWNER, confirmation='DELETE') == {'deleted': True}
    assert calls == ['clear', 'clear', 'auth']


def test_invalid_confirmation_never_deletes(monkeypatch):
    monkeypatch.setattr(service, 'delete_learning_data', lambda **_: pytest.fail('deleted'))
    with pytest.raises(HTTPException) as error: service.delete_account(user_id=OWNER, confirmation='no')
    assert error.value.status_code == 422


@pytest.mark.parametrize('mode,status', [('deleted',401), ('auth403',401), ('outage',503), ('mismatch',401), ('valid',200)])
def test_signed_jwt_requires_live_account(monkeypatch, mode, status):
    monkeypatch.setattr(settings, 'supabase_jwt_secret', 'test-secret-at-least-thirty-two-bytes')
    token = jwt.encode({'sub': OWNER, 'aud': 'authenticated'}, settings.supabase_jwt_secret, algorithm='HS256')
    def get_user(value):
        assert value == token
        if mode == 'auth403': raise AuthApiError('private', 403, None)
        if mode == 'outage': raise RuntimeError('private')
        return NS(user=None if mode == 'deleted' else NS(id=OWNER if mode == 'valid' else str(UUID(int=2))))
    monkeypatch.setattr(deps, 'get_supabase_client', lambda: NS(auth=NS(get_user=get_user)))
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
    if status == 200:
        assert deps.get_current_user(credentials).id == OWNER
    else:
        with pytest.raises(HTTPException) as error: deps.get_current_user(credentials)
        assert error.value.status_code == status and 'private' not in str(error.value.detail)
