from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import product_analytics_service as service


@pytest.fixture
def owned_client():
    previous = app.dependency_overrides.copy()
    owner = str(uuid4())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=owner, email=None)
    try:
        with TestClient(app) as client: yield client, owner
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_learning_outcome_api_requires_authentication():
    assert TestClient(app).get('/api/v1/recommendations/learning-outcomes').status_code == 401


@pytest.mark.parametrize('days', ['0', '91', '-1', 'null', '1.5'])
def test_learning_outcome_rejects_invalid_windows(owned_client, days):
    client, _ = owned_client
    assert client.get('/api/v1/recommendations/learning-outcomes', params={'days': days}).status_code == 422


def test_outcome_scope_comes_from_auth_and_default_allows_mature_cohorts(owned_client, monkeypatch):
    client, owner = owned_client
    calls = []
    def outcomes(**kwargs):
        calls.append(kwargs)
        return {'cohorts': [], 'masteryCalibration': []}
    monkeypatch.setattr(service, 'learning_outcomes', outcomes)
    response = client.get('/api/v1/recommendations/learning-outcomes', params={'user_id': str(uuid4())})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert calls == [{'user_id': owner, 'days': 30}]
    assert response.json()['masteryCalibration'] == []


@pytest.mark.parametrize('days', [1, 90])
def test_outcome_api_preserves_valid_window(owned_client, monkeypatch, days):
    client, owner = owned_client
    def outcomes(**kwargs):
        assert kwargs == {'user_id': owner, 'days': days}
        return {'horizonDays': 7, 'cohorts': [{'mature': 0, 'completionRate': None}]}
    monkeypatch.setattr(service, 'learning_outcomes', outcomes)
    response = client.get('/api/v1/recommendations/learning-outcomes', params={'days': days})
    assert response.status_code == 200 and response.json()['cohorts'][0]['completionRate'] is None


def test_service_uses_database_aggregation_not_row_capped_client_reads(monkeypatch):
    calls = []
    def rpc(name, params):
        calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={'cohorts': [{'total': 2001}]}))
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(rpc=rpc))
    result = service.learning_outcomes(user_id='owner', days=30)
    assert result['cohorts'][0]['total'] == 2001
    assert calls == [('learning_outcome_metrics', {'p_user': 'owner', 'p_days': 30})]
