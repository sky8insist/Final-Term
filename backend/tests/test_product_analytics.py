from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import product_analytics_service as service


def recommendation():
    return {'algorithmVersion': 'next-action-v2', 'generatedAt': '2026-10-27T00:00:00+00:00',
            'actions': [{'id': 'topic', 'subjectId': 'subject', 'knowledgePointId': 'topic',
                         'priorityScore': .7, 'reasons': ['evidence'], 'inputSignals': {'mastery': .2},
                         'scoreComponents': {'need': .7}, 'href': '/guided-study?topicId=topic'}]}


def test_delivery_persists_frozen_owned_evidence_without_mutating_scoring_result(monkeypatch):
    inserted = []
    class Query:
        def insert(self, rows): inserted.extend(deepcopy(rows)); return self
        def execute(self): return SimpleNamespace(data=inserted)
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(table=lambda name: Query()))
    original = recommendation()
    result = service.deliver(user_id='owner', result=original)
    original['actions'][0]['inputSignals']['mastery'] = .9
    assert inserted[0]['snapshot']['inputSignals']['mastery'] == .2
    assert inserted[0]['user_id'] == 'owner'
    assert inserted[0]['snapshot']['algorithmVersions']['learnerState'] == 'learner-state-v1'
    assert result['actions'][0]['recommendationId'] == inserted[0]['id']
    assert 'recommendationId=' in result['actions'][0]['href']
    assert 'recommendationId' not in original['actions'][0]
    assert 'recommendationId=' not in inserted[0]['snapshot']['href']


def test_failed_audit_write_never_returns_an_unpersisted_tracking_id(monkeypatch):
    def fail(*args): raise RuntimeError('DB unavailable')
    monkeypatch.setattr(service, 'get_supabase_client', fail)
    with pytest.raises(RuntimeError): service.deliver(user_id='owner', result=recommendation())


def test_empty_delivery_does_not_write_or_fabricate_impressions(monkeypatch):
    monkeypatch.setattr(service, 'get_supabase_client', lambda: pytest.fail('Empty actions must not write'))
    assert service.deliver(user_id='owner', result={**recommendation(), 'actions': []})['actions'] == []


@pytest.mark.parametrize(('code', 'status'), [('42501', 404), ('22023', 409)])
def test_feedback_maps_absent_or_expired_records(monkeypatch, code, status):
    class Failure(Exception): pass
    error = Failure('private internal error')
    error.code = code
    class RPC:
        def execute(self): raise error
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(rpc=lambda *args: RPC()))
    with pytest.raises(HTTPException) as exc:
        service.record_feedback(user_id='owner', recommendation_id='id', event='clicked')
    assert exc.value.status_code == status and 'private internal error' not in str(exc.value.detail)


@pytest.fixture
def client():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(uuid4()), email=None)
    try:
        with TestClient(app) as value: yield value
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize('payload', [{'event': 'session.completed'}, {'event': 'mastery.changed'},
                                    {'event': 'clicked', 'score': .9}, {'event': 'impression', 'createdAt': 'yesterday'}])
def test_client_cannot_supply_learning_results_or_event_time(client, payload):
    assert client.post(f'/api/v1/recommendations/{uuid4()}/feedback', json=payload).status_code == 422


@pytest.mark.parametrize('days', [0, 91])
def test_metrics_window_is_bounded(client, days):
    assert client.get('/api/v1/recommendations/quality-metrics', params={'days': days}).status_code == 422


def test_plain_recommendation_get_remains_read_only_and_no_store(client, monkeypatch):
    import app.api.recommendations as api
    monkeypatch.setattr(api, 'next_actions', lambda **kwargs: recommendation())
    monkeypatch.setattr(service, 'deliver', lambda **kwargs: pytest.fail('Read-only lookup wrote audit rows'))
    response = client.get('/api/v1/recommendations/next-actions')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert 'recommendationId' not in response.json()['actions'][0]


def test_feedback_metrics_and_audit_require_authentication():
    with TestClient(app) as client:
        for method, path in [('get', '/api/v1/recommendations/quality-metrics'),
                             ('get', f'/api/v1/recommendations/{uuid4()}/audit'),
                             ('post', f'/api/v1/recommendations/{uuid4()}/feedback')]:
            assert getattr(client, method)(path).status_code == 401
