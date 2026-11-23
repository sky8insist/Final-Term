import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import product_analytics_service as service


def encoded(**changes):
    payload = {'v': 1, 'scope': 'history:owner', 'at': '2026-10-27T00:00:00+08:00', 'id': str(uuid4()), **changes}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')


@pytest.mark.parametrize('change', [{'v': True}, {'v': 2}, {'scope': 'history:other'}, {'at': '2026-10-27'},
                                    {'at': '2026-10-27T00:00:00),id.gt.any'}, {'id': 'bad'}, {'id': 4}, {'at': None}, {'extra': 1}])
def test_cursor_is_scoped_strict_and_cannot_inject_filters(change):
    with pytest.raises(HTTPException) as exc: service._cursor(encoded(**change), 'history:owner')
    assert exc.value.status_code == 422


@pytest.mark.parametrize('value', ['bad!', 'a'*1025, base64.b64encode(b'[]').decode(), base64.b64encode(b'null').decode()])
def test_broken_cursor_is_a_validation_error_not_server_error(value):
    with pytest.raises(HTTPException) as exc: service._cursor(value, 'history:owner')
    assert exc.value.status_code == 422


def test_valid_cursor_normalizes_timezone_before_building_filter():
    expected = str(uuid4())
    at, row_id = service._cursor(encoded(id=expected), 'history:owner')
    assert at == '2026-10-26T16:00:00+00:00' and row_id == expected


def test_page_uses_lookahead_and_cursor_last_delivered_not_extra_row():
    rows = [{'id': str(uuid4()), 'created_at': '2026-10-27T00:00:00+00:00'} for _ in range(3)]
    class Query:
        def order(self, *args, **kwargs): return self
        def limit(self, limit): assert limit == 3; return self
        def execute(self): return SimpleNamespace(data=rows)
    page = service._page(Query(), scope='history:owner', cursor=None, limit=2)
    assert page['items'] == rows[:2] and page['hasMore']
    assert service._cursor(page['nextCursor'], 'history:owner')[1] == rows[1]['id']


@pytest.fixture
def client():
    previous = app.dependency_overrides.copy()
    owner = str(uuid4())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=owner, email=None)
    try:
        with TestClient(app) as value: yield value, owner
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(previous)


@pytest.mark.parametrize('path', ['/history?limit=0', '/history?limit=101', '/prediction-coverage?days=0', '/prediction-coverage?days=91'])
def test_new_read_endpoints_bound_query_parameters(client, path):
    value, _ = client
    assert value.get('/api/v1/recommendations'+path).status_code == 422


def test_authenticated_scope_overrides_client_user_parameter(client, monkeypatch):
    value, owner = client
    calls = []
    def coverage(**kwargs): calls.append(kwargs); return {'coverageRate': None}
    monkeypatch.setattr(service, 'prediction_coverage', coverage)
    response = value.get('/api/v1/recommendations/prediction-coverage', params={'user_id': str(uuid4())})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['coverageRate'] is None
    assert calls == [{'user_id': owner, 'days': 30}]


def test_paging_and_coverage_require_authentication():
    with TestClient(app) as value:
        assert value.get('/api/v1/recommendations/history').status_code == 401
        assert value.get('/api/v1/recommendations/prediction-coverage').status_code == 401
