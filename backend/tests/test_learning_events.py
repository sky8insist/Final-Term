from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import learning_job_service as service, daily_review_service

OWNER,SUBJECT,JOB,TOKEN=[str(UUID(int=i)) for i in range(1,5)]


def test_event_consumer_duplicate_delivery_three_times_never_recomputes_twice(monkeypatch):
    calls=[];claimed=False
    def rpc(name,values):
        nonlocal claimed
        calls.append((name,values))
        if name=='claim_learning_job':
            if claimed:return None
            claimed=True;return {'kind':'projection_refresh','claim_token':TOKEN}
        assert name=='consume_learning_projection_job'
        return {'consumed':True,'projectionVersion':1}
    monkeypatch.setattr(service,'rpc',rpc)
    monkeypatch.setattr(daily_review_service,'build_learning_review_graph',lambda:pytest.fail('Event invoked graph'))
    assert service.run(JOB)['projectionVersion']==1
    for _ in range(3):assert service.run(JOB)=={'status':'skipped'}
    assert sum(name=='consume_learning_projection_job' for name,_ in calls)==1
    assert calls[1][1]=={'p_job':JOB,'p_token':TOKEN}


def test_consumer_failure_leaves_retry_to_durable_queue_with_sanitized_code(monkeypatch):
    calls=[]
    def rpc(name,values):
        calls.append((name,values))
        if name=='claim_learning_job':return {'kind':'projection_refresh','claim_token':TOKEN}
        if name=='consume_learning_projection_job':raise RuntimeError('private database information')
        assert name=='finish_learning_job';return True
    monkeypatch.setattr(service,'rpc',rpc)
    assert service.run(JOB)=={'status':'retry_or_dead'}
    assert calls[-1][1]['p_error']=='RuntimeError' and calls[-1][1]['p_token']==TOKEN


@pytest.mark.parametrize('code,status',[('42501',404),('40001',409),('40P01',409),('22023',422)])
def test_user_retry_errors_hide_database_details(monkeypatch,code,status):
    class Failure(Exception):pass
    exc=Failure('private');exc.code=code
    def fail(*_):raise exc
    monkeypatch.setattr(service,'rpc',fail)
    with pytest.raises(HTTPException) as error:service.retry(user_id=OWNER,job_id=JOB)
    assert error.value.status_code==status and 'private' not in error.value.detail


def test_status_and_retry_api_keep_authenticated_owner(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'retry',lambda **values:calls.append(values) or {'status':'queued'})
    monkeypatch.setattr(service,'list_jobs',lambda **values:calls.append(values) or [])
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            assert client.post(f'/api/v1/learning-jobs/{JOB}/retry').status_code==200
            assert calls[0]=={'user_id':OWNER,'job_id':JOB}
            assert client.get('/api/v1/learning-jobs',params={'subject_id':SUBJECT}).status_code==200
            assert calls[1]=={'user_id':OWNER,'subject_id':SUBJECT}
            assert client.post('/api/v1/learning-jobs/invalid/retry').status_code==422
    finally:app.dependency_overrides.pop(get_current_user,None)
    with TestClient(app) as client:
        assert client.post(f'/api/v1/learning-jobs/{JOB}/retry').status_code==401
        assert client.get('/api/v1/learning-jobs',params={'subject_id':SUBJECT}).status_code==401


def test_job_status_query_does_not_expose_lease_tokens(monkeypatch):
    calls=[]
    class Client:
        def table(self,name):calls.append(name);return self
        def select(self,columns):calls.append(columns);return self
        def eq(self,key,value):calls.append((key,value));return self
        def order(self,*_,**__):return self
        def limit(self,n):assert n==50;return self
        def execute(self):return SimpleNamespace(data=[])
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client())
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    assert service.list_jobs(user_id=OWNER,subject_id=SUBJECT)==[]
    assert ('user_id',OWNER) in calls and ('subject_id',SUBJECT) in calls and 'claim_token' not in calls[1]


def test_job_status_requires_owned_subject_before_reading_jobs(monkeypatch):
    def reject(**_):raise HTTPException(404,'Missing')
    monkeypatch.setattr(service,'get_subject',reject)
    monkeypatch.setattr(service,'get_supabase_client',lambda:pytest.fail('Unauthorized job read'))
    with pytest.raises(HTTPException):service.list_jobs(user_id=OWNER,subject_id=SUBJECT)


def test_sweep_captures_missed_events_before_dispatch(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'rpc',lambda name,values:calls.append(name) or [])
    assert service.sweep()=={'dispatched':0,'dispatchFailed':0}
    assert calls==['enqueue_daily_review_jobs','enqueue_learning_due_events','ready_learning_jobs']
