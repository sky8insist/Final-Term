from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import daily_review_service as service

OWNER, SUBJECT, REQUEST = [str(UUID(int=i)) for i in range(1,4)]


def source():
    return {'day':'2026-10-22','timezone':'Asia/Shanghai','topics':[
        {'id':'t','title':'Position Encoding','mastery':{'mastery':.4,'confidence':.7,'attempts':3},'covered':True,'before':.28,'after':.4,'lastEvidenceId':'e'}],
        'completedTasks':[],'submittedTodayGradedAttempts':1,'learningEvents':{'qa':2},'tomorrowTasks':[],
        'exams':[],'capacity':60,'usedMinutes':30,'candidates':[
            {'id':'task','planId':'plan','planVersion':1,'topicId':'t','minutes':20,'title':'Practice','from':'2026-10-22'}]}


def run(value):return service.build_learning_review_graph().invoke({'source':value})['report']


def test_graph_reports_evidenced_percentage_point_delta_and_weak_topic():
    report=run(source())
    assert report['masteryChanges'][0]['deltaPoints']==12
    assert report['masteryChanges'][0]['evidenceId']=='e'
    assert report['tomorrowRecommendations'][0]['title']=='Position Encoding'
    assert report['requiresConfirmation'] and report['feasibility']['withinBudget']


@pytest.mark.parametrize('before,after,evidence,expected',[(None,.4,'e',None),(.8,.4,'e',-40),(.4,.4,'e',0),(.3,None,None,'absent')])
def test_delta_never_invents_missing_baseline_or_history(before,after,evidence,expected):
    value=source(); value['topics'][0].update(before=before,after=after,lastEvidenceId=evidence)
    changes=run(value)['masteryChanges']
    if expected=='absent':assert changes==[]
    else:assert changes[0]['deltaPoints']==expected


@pytest.mark.parametrize('capacity,used,count,feasible',[(None,0,0,None),(10,20,0,False),(60,50,0,True),(60,30,1,True)])
def test_critic_respects_shared_capacity_and_unknown_budget(capacity,used,count,feasible):
    value=source();value.update(capacity=capacity,usedMinutes=used)
    report=run(value)
    assert len(report['proposedMoves'])==count and report['feasibility']['withinBudget']==feasible
    assert report['requiresConfirmation']==bool(count)


def test_unassessed_topic_is_not_reported_as_weak_or_default_fifty_percent():
    value=source();value['topics'][0]['mastery']=None
    report=run(value)
    assert report['unresolvedProblems']==[] and report['proposedMoves']==[]


def test_mastered_topic_is_not_promoted_to_remediation():
    value=source();value['topics'][0]['mastery']={'mastery':.95,'confidence':.8,'attempts':3,'metadata':{'assessmentCount':3,'assessmentCorrectStreak':3}}
    assert run(value)['tomorrowRecommendations']==[]


@pytest.mark.parametrize('mode',['duplicate','forged','capacity'])
def test_critic_rejects_invalid_drafts(mode):
    value=source();report=run(value)
    if mode=='duplicate':report['proposedMoves']*=2
    elif mode=='forged':report['proposedMoves'][0]['minutes']=1
    else:value['capacity']=0
    with pytest.raises(ValueError):service.critic({'source':value,'report':report})


def test_proposals_are_bounded_and_repeatable():
    value=source();value.update(capacity=1000,usedMinutes=0)
    value['candidates']=[{**value['candidates'][0],'id':f'task{i}'} for i in range(8)]
    assert len(run(value)['proposedMoves'])==3
    assert run(value)==run(deepcopy(value))
    for candidate in value['candidates']:candidate['slotKey']='same-plan-topic-type'
    assert len(run(value)['proposedMoves'])==1


@pytest.mark.parametrize('code,status',[('42501',404),('40001',409),('22023',422)])
def test_rpc_errors_hide_internal_information(monkeypatch,code,status):
    class Failure(Exception):pass
    error=Failure('private');error.code=code
    def fail(*_):raise error
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace(rpc=fail))
    with pytest.raises(HTTPException) as exc:service.rpc('read',{})
    assert exc.value.status_code==status and 'private' not in exc.value.detail


@pytest.mark.parametrize('body',[{'subjectId':SUBJECT,'requestId':REQUEST,'report':{}},
    {'subjectId':'invalid','requestId':REQUEST},{'subjectId':SUBJECT}])
def test_api_rejects_fabricated_context_or_invalid_shape(body):
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:assert client.post('/api/v1/daily-reviews',json=body).status_code==422
    finally:app.dependency_overrides.pop(get_current_user,None)


def test_decision_api_requires_real_boolean_and_uses_owner(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'decide',lambda **values:calls.append(values) or {'status':'applied'})
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            assert client.post(f'/api/v1/daily-reviews/{REQUEST}/decision',json={'version':1,'approve':'yes'}).status_code==422
            assert client.post(f'/api/v1/daily-reviews/{REQUEST}/decision',json={'version':1,'approve':True}).status_code==200
            assert calls==[{'user_id':OWNER,'review_id':REQUEST,'version':1,'approve':True}]
    finally:app.dependency_overrides.pop(get_current_user,None)
    with TestClient(app) as client:
        assert client.post('/api/v1/daily-reviews',json={'subjectId':SUBJECT,'requestId':REQUEST}).status_code==401
        assert client.get(f'/api/v1/daily-reviews/{REQUEST}').status_code==401


def test_create_replay_does_not_regenerate_old_report(monkeypatch):
    class Client:
        def table(self,*_):return self
        def select(self,*_):return self
        def eq(self,*_):return self
        def limit(self,*_):return self
        def execute(self):return SimpleNamespace(data=[{'id':REQUEST,'subject_id':SUBJECT,'day':'2026-10-21'}])
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client())
    monkeypatch.setattr(service,'rpc',lambda *_:pytest.fail('Replay regenerated'))
    assert service.create(user_id=OWNER,subject_id=SUBJECT,request_id=REQUEST)['day']=='2026-10-21'
    with pytest.raises(HTTPException) as error:service.create(user_id=OWNER,subject_id=REQUEST,request_id=REQUEST)
    assert error.value.status_code==409
