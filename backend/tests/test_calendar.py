from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import calendar_service as service, study_plan_v3_service as plans

OWNER,SUBJECT,MATERIAL,BLOCK,PROPOSAL=[str(UUID(int=index)) for index in range(1,6)]
DAY=date(2026,10,19)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):monkeypatch.setattr(service,'today',lambda:DAY)


@pytest.mark.parametrize('text,expected',[
    ('Final Exam: 2026-12-20\nChapter 1-6','2026-12-20'),
    ('期末考试：2026/12/20\n第一至六章','2026-12-20'),
    ('Midterm: 2026-11-04','2026-11-04'),
    ('Final Exam: 2026-2-30',None),
    ('Final Exam: 2025-12-20',None),
    ('Final Exam: 12/20',None),
    ('Final Exam: 12/20/2026',None),
    ('Final Exam: 2030-12-20',None),
    ('Lecture: 2026-12-20',None),
])
def test_explicit_exam_dates_only_no_year_or_topic_inference(text,expected):
    result=service.extract_candidates(text)
    assert (result[0]['exam_date'] if result else None)==expected
    if 'Chapter' in text:assert result[0]['scope_text']=='Chapter 1-6'


@pytest.mark.parametrize('offset',[-1,42])
def test_calendar_rejects_invalid_ranges_without_db(monkeypatch,offset):
    monkeypatch.setattr(service,'rpc',lambda *_:pytest.fail('Unexpected DB access'))
    with pytest.raises(HTTPException) as error:service.calendar(user_id=OWNER,start=DAY,end=DAY+timedelta(days=offset))
    assert error.value.status_code==422


def test_daily_conflicts_and_missed_status_come_from_authoritative_data(monkeypatch):
    row={'date':(DAY-timedelta(days=1)).isoformat(),'minutes':30,'plannedMinutes':60,'tasks':[{'status':'pending'},{'status':'completed'},{'status':'skipped'}],'exams':[{'id':'1'},{'id':'2'}]}
    calls=[]
    monkeypatch.setattr(service,'rpc',lambda name,values:calls.append((name,values)) or [deepcopy(row)])
    result=service.calendar(user_id=OWNER,start=DAY,end=DAY,subject_id=SUBJECT)
    assert result['days'][0]['overCapacity'] and result['days'][0]['examConflict'] and result['days'][0]['missedCount']==1
    assert calls[0][1]['p_user']==OWNER and calls[0][1]['p_subject']==SUBJECT
    row['minutes']=None;row['exams']=[]
    assert service.calendar(user_id=OWNER,start=DAY,end=DAY)['days'][0]['overCapacity'] is False


@pytest.mark.parametrize('code,status',[('40001',409),('40P01',409),('42501',404),('23503',404),('22023',422),('23514',422)])
def test_private_rpc_errors_map_without_database_details(monkeypatch,code,status):
    class Failure(Exception):pass
    error=Failure('private database detail');error.code=code
    def fail(*args,**kwargs):raise error
    monkeypatch.setattr(service,'get_supabase_client',lambda:SimpleNamespace(rpc=fail))
    with pytest.raises(HTTPException) as result:service.rpc('operation',{})
    assert result.value.status_code==status and 'private database detail' not in result.value.detail


class Query:
    def __init__(self,client,table):self.client,self.table=client,table;self.filters=[]
    def select(self,*args):return self
    def eq(self,key,value):self.filters.append((key,value));return self
    def in_(self,key,values):self.ids=values;return self
    def order(self,*args,**kwargs):return self
    def limit(self,*args):return self
    def upsert(self,values,**kwargs):self.client.writes.append((deepcopy(values),kwargs));return self
    def execute(self):
        if self.table=='content_blocks':
            self.client.scope=self.filters
            return SimpleNamespace(data=self.client.blocks)
        return SimpleNamespace(data=[{'id':PROPOSAL,'fingerprint':values[0]['fingerprint']} for values in self.client.writes])


class Client:
    def __init__(self,blocks):self.blocks,self.writes,self.scope=blocks,[],[]
    def table(self,name):return Query(self,name)


def test_proposal_uses_canonical_owned_ready_blocks_and_no_exam_write(monkeypatch):
    db=Client([{'id':BLOCK,'content_text':'Final Exam: 2026-12-20'},{'id':MATERIAL,'content_text':'Chapter 1-6'}])
    monkeypatch.setattr(service,'get_supabase_client',lambda:db)
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    scopes=[]
    monkeypatch.setattr(service,'_owned',lambda **values:scopes.append(values) or {'status':'ready'})
    evidence=[{'id':BLOCK,'chunkText':'Canonical original','filename':'syllabus.pdf'}]
    monkeypatch.setattr(service.notes_service,'canonical_sources',lambda **_:evidence)
    first=service.propose(user_id=OWNER,subject_id=SUBJECT,material_id=MATERIAL)
    second=service.propose(user_id=OWNER,subject_id=SUBJECT,material_id=MATERIAL)
    assert first['candidateCount']==1 and second['candidateCount']==1
    assert db.writes[0][0]['fingerprint']==db.writes[1][0]['fingerprint']
    assert db.writes[0][0]['evidence']==evidence and db.writes[0][0]['scope_text']=='Chapter 1-6'
    assert db.writes[0][1]['ignore_duplicates'] is True
    assert ('user_id',OWNER) in db.scope and ('subject_id',SUBJECT) in db.scope and ('material_id',MATERIAL) in db.scope
    assert scopes[0]['user_id']==OWNER and scopes[0]['subject_id']==SUBJECT


def test_unready_syllabus_rejected_before_blocks(monkeypatch):
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    monkeypatch.setattr(service,'_owned',lambda **_:{'status':'parsing'})
    monkeypatch.setattr(service,'get_supabase_client',lambda:pytest.fail('Unready source read'))
    with pytest.raises(HTTPException) as error:service.propose(user_id=OWNER,subject_id=SUBJECT,material_id=MATERIAL)
    assert error.value.status_code==409


def test_proposal_limit_and_source_truncation_are_bounded(monkeypatch):
    db=Client([{'id':str(UUID(int=index+100)),'content_text':'Final Exam: 2026-12-20'} for index in range(501)])
    monkeypatch.setattr(service,'get_supabase_client',lambda:db)
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    monkeypatch.setattr(service,'_owned',lambda **_:{'status':'ready'})
    monkeypatch.setattr(service.notes_service,'canonical_sources',lambda **values:[{'id':value,'chunkText':'Evidence'} for value in values['block_ids']])
    result=service.propose(user_id=OWNER,subject_id=SUBJECT,material_id=MATERIAL)
    assert result['truncated'] and len(db.writes)==20


@pytest.mark.parametrize('requested,shared,expected', [({DAY.isoformat():50},20,20),({},120,60),({DAY.isoformat():0},120,0),({DAY.isoformat():50},120,50)])
def test_plan_prepare_clamps_shared_capacity_but_preserves_user_preferences(monkeypatch,requested,shared,expected):
    from app.services import study_plan_service,subject_service
    class PlanQuery:
        def select(self,*args):return self
        def eq(self,*args):return self
        def order(self,*args,**kwargs):return self
        def limit(self,*args):return self
        def execute(self):return SimpleNamespace(data=[])
    db=SimpleNamespace(table=lambda *_:PlanQuery(),rpc=lambda name,values:SimpleNamespace(execute=lambda:SimpleNamespace(data={DAY.isoformat():shared})))
    monkeypatch.setattr(plans,'get_supabase_client',lambda:db)
    monkeypatch.setattr(subject_service,'get_subject',lambda **_:None)
    monkeypatch.setattr(study_plan_service,'_today',lambda:DAY)
    monkeypatch.setattr(plans.study_signal_service,'collect_study_signals',lambda **_:{'signals':[],'warnings':[]})
    monkeypatch.setattr(plans.learner_state_service,'list_states',lambda **_:{'topics':[]})
    captured=[]
    monkeypatch.setattr(study_plan_service,'build_schedule',lambda **values:captured.append(values) or {'tasks':[],'warnings':[]})
    result=plans.prepare(user_id=OWNER,subject_id=SUBJECT,exam_date=(DAY+timedelta(days=3)).isoformat(),daily_minutes=60,
        reserve_final_day=True,weekend_extra=False,available_minutes=requested)
    assert captured[0]['available_minutes'][DAY.isoformat()]==expected
    assert result['available']==requested


def test_learning_data_deletion_clears_personal_availability(monkeypatch):
    from app.services import privacy_service
    from app.services import workspace_cache_service
    revoked=[]
    monkeypatch.setattr(workspace_cache_service,'reset_user_snapshots',lambda **values:revoked.append(values))
    calls=[]
    monkeypatch.setattr(privacy_service, '_owned_rows', lambda *a: [])
    def rpc(name, params):
        calls.append((name, params))
        return SimpleNamespace(execute=lambda: None)
    monkeypatch.setattr(privacy_service,'get_supabase_client',lambda:SimpleNamespace(rpc=rpc))
    assert privacy_service.delete_learning_data(user_id=OWNER)['deleted']
    assert calls == [('delete_privacy_learning_data', {'p_user': OWNER})]
    assert revoked==[{'user_id':OWNER}]


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as value:yield value
    finally:app.dependency_overrides.pop(get_current_user,None)


@pytest.mark.parametrize('payload',[{'minutes':-1,'version':0},{'minutes':1441,'version':0},{'minutes':30,'version':-1},{'minutes':30,'version':0,'user_id':'forged'}])
def test_availability_validation(client,payload):
    assert client.put('/api/v1/calendar/availability/2026-10-20',json=payload).status_code==422


def test_api_delegates_owner_and_versions(client,monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'save_availability',lambda **values:calls.append(values) or {'version':1})
    assert client.put('/api/v1/calendar/availability/2026-10-20',json={'minutes':60,'version':0}).status_code==200
    assert calls[-1]=={'user_id':OWNER,'day':date(2026,10,20),'minutes':60,'version':0}
    monkeypatch.setattr(service,'move_task',lambda **values:calls.append(values) or {})
    assert client.post(f'/api/v1/calendar/tasks/{BLOCK}/move',json={'day':'2026-10-21','version':2}).status_code==200
    assert calls[-1]['task_id']==BLOCK and calls[-1]['user_id']==OWNER and calls[-1]['version']==2
    monkeypatch.setattr(service,'confirm',lambda **values:calls.append(values) or {'id':BLOCK})
    assert client.post(f'/api/v1/calendar/exam-proposals/{PROPOSAL}/confirm',json={'title':'Final','exam_date':'2026-12-20','topics':[{'knowledge_point_id':BLOCK,'weight':1}]}).status_code==200
    assert calls[-1]['proposal_id']==PROPOSAL and calls[-1]['user_id']==OWNER


def test_calendar_requires_login_and_valid_ids():
    with TestClient(app) as client:assert client.get('/api/v1/calendar',params={'start':'2026-10-19','end':'2026-10-20'}).status_code==401
