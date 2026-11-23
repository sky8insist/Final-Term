from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.models.conversion import ConversionSource
from app.services import mind_map_topic_service as service, conversion_service

OWNER, SUBJECT, ART, TOPIC = [str(UUID(int=i)) for i in range(1, 5)]


def overlay(mastery=None, bound=True, covered=False):
    return {'artifactVersion': 2, 'nodes': {'n': {'knowledgePointId': TOPIC if bound else None,
        'mastery': mastery, 'covered': covered, 'bindingVersion': 1, 'stale': False, 'dueCards': 0, 'exams': []}}}


@pytest.mark.parametrize('bound,covered,state', [(False, False, 'unbound'), (True, False, 'not_started'), (True, True, 'covered')])
def test_no_assessment_never_displays_default_mastery(monkeypatch, bound, covered, state):
    monkeypatch.setattr(service, 'rpc', lambda *_: overlay(bound=bound, covered=covered))
    row = service.learning(user_id=OWNER, artifact_id=ART)['nodes']['n']
    assert row['state'] == state and row['masteryScore'] is None and row['masteryConfidence'] is None


@pytest.mark.parametrize('metadata,state', [({}, 'practicing'),
    ({'assessmentCount': 3, 'assessmentCorrectStreak': 3}, 'mastered'),
    ({'misconceptionRisk': .9}, 'at_risk'), ({'flashcardRecallRisk': True}, 'at_risk')])
def test_live_state_uses_canonical_assessment_thresholds(monkeypatch, metadata, state):
    row = {'mastery': .93, 'confidence': .8, 'attempts': 3, 'metadata': metadata, 'last_reviewed_at': '2026-10-21T00:00:00Z'}
    monkeypatch.setattr(service, 'rpc', lambda *_: overlay(deepcopy(row)))
    value = service.learning(user_id=OWNER, artifact_id=ART)['nodes']['n']
    assert value['state'] == state and value['masteryScore'] == .93
    assert value['lastReviewAt'] == row['last_reviewed_at'] and 'mastery' not in value


@pytest.mark.parametrize('code,status', [('42501',404),('40001',409),('40P01',409),('22023',422),('23503',422)])
def test_rpc_error_contract(monkeypatch, code, status):
    class Failure(Exception): pass
    failure = Failure('private details'); failure.code = code
    def fail(*_): raise failure
    monkeypatch.setattr(service, 'get_supabase_client', lambda: SimpleNamespace(rpc=fail))
    with pytest.raises(HTTPException) as error: service.rpc('read', {})
    assert error.value.status_code == status and 'private details' not in error.value.detail


@pytest.mark.parametrize('topic,version,expected', [(TOPIC,2,[TOPIC]),(None,2,[]),(TOPIC,3,None)])
def test_conversion_only_inherits_effective_node_topic(monkeypatch, topic, version, expected):
    from test_conversions import Client, CITATIONS, BLOCK
    monkeypatch.setattr(conversion_service, '_owned', lambda **_: {'artifact_type':'mind_map', 'version':2, 'title':'Map',
        'content':{'nodes':[{'id':'n','citationIds':[BLOCK]}]}})
    monkeypatch.setattr(conversion_service, 'get_supabase_client', lambda: Client({'artifact_topics':[{'knowledge_point_id':ART}]}))
    monkeypatch.setattr(conversion_service.notes_service, 'canonical_sources', lambda **_: CITATIONS)
    monkeypatch.setattr(service, 'learning', lambda **_: {'artifactVersion':version, 'nodes':{'n':{'knowledgePointId':topic}}})
    source = ConversionSource(kind='mind_map_node',id=ART,version=2,nodeId='n')
    if expected is None:
        with pytest.raises(HTTPException) as error: conversion_service.snapshot_source(user_id=OWNER, subject_id=SUBJECT, source=source)
        assert error.value.status_code == 409
    else:
        assert conversion_service.snapshot_source(user_id=OWNER, subject_id=SUBJECT, source=source)['topicIds'] == expected


@pytest.mark.parametrize('body', [{'artifactVersion':0,'bindingVersion':0}, {'artifactVersion':1,'bindingVersion':-1},
    {'artifactVersion':1,'bindingVersion':0,'topicId':'wrong'}, {'artifactVersion':1,'bindingVersion':0,'user_id':OWNER}])
def test_binding_api_rejects_invalid_or_forged_fields(body):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            assert client.put(f'/api/v1/artifacts/{ART}/nodes/n/topic', json=body).status_code == 422
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_binding_api_uses_authenticated_owner_and_versions(monkeypatch):
    calls = []
    monkeypatch.setattr(service, 'bind', lambda **values: calls.append(values) or {'artifactVersion':3,'bindingVersion':2})
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            response = client.put(f'/api/v1/artifacts/{ART}/nodes/n/topic', json={'topicId':TOPIC,'artifactVersion':2,'bindingVersion':1})
            assert response.status_code == 200
            assert calls == [dict(user_id=OWNER,artifact_id=ART,node_id='n',topic_id=TOPIC,artifact_version=2,binding_version=1)]
    finally: app.dependency_overrides.pop(get_current_user, None)


def test_map_learning_requires_authentication():
    with TestClient(app) as client:
        assert client.get(f'/api/v1/artifacts/{ART}/learning').status_code == 401
        assert client.put(f'/api/v1/artifacts/{ART}/nodes/n/topic', json={'artifactVersion':1,'bindingVersion':0}).status_code == 401
