from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import learning_job_service as service, daily_review_service

OWNER,SUBJECT,JOB,TOKEN=[str(UUID(int=i)) for i in range(1,5)]


def test_duplicate_delivery_never_runs_graph(monkeypatch):
    monkeypatch.setattr(service,'rpc',lambda *_:None)
    monkeypatch.setattr(daily_review_service,'build_learning_review_graph',lambda:pytest.fail('Duplicate executed'))
    for _ in range(3):assert service.run(JOB)=={'status':'skipped'}


@pytest.mark.parametrize('fails',[False,True])
def test_automatic_publication_uses_claim_and_never_decides_plan(monkeypatch,fails):
    calls=[]
    def rpc(name,values):
        calls.append((name,values))
        if name=='claim_learning_job':return {'kind':'daily_review','user_id':OWNER,'subject_id':SUBJECT,'day':'2026-10-22','claim_token':TOKEN}
        if name=='publish_daily_review_job':
            if fails:raise RuntimeError('private')
            return {'id':JOB}
        return True
    monkeypatch.setattr(service,'rpc',rpc)
    monkeypatch.setattr(daily_review_service,'rpc',lambda *_:{'source':'canonical'})
    monkeypatch.setattr(daily_review_service,'build_learning_review_graph',lambda:SimpleNamespace(invoke=lambda _: {'report':{'proposedMoves':[]}}))
    result=service.run(JOB)
    assert result['status']==('retry_or_dead' if fails else 'succeeded')
    assert calls[1][0]=='publish_daily_review_job' and calls[1][1]['p_token']==TOKEN
    assert not any(name=='decide_daily_learning_review' for name,_ in calls)
    if fails:assert calls[2][1]['p_error']=='RuntimeError'


def test_dispatch_failure_preserves_durable_jobs_and_continues(monkeypatch):
    from app.worker import tasks
    monkeypatch.setattr(service,'rpc',lambda name,_:0 if name=='enqueue_daily_review_jobs' else ['first','second'])
    seen=[]
    def dispatch(value):
        seen.append(value)
        if value=='first':raise RuntimeError('broker offline')
    monkeypatch.setattr(tasks.process_learning_job,'delay',dispatch)
    assert service.sweep()=={'dispatched':1,'dispatchFailed':1}
    assert seen==['first','second']


@pytest.mark.parametrize('body',[{'enabled':'yes','hour':22,'version':0},{'enabled':True,'hour':24,'version':0},
    {'enabled':True,'hour':22,'version':-1},{'enabled':True,'hour':22,'version':0,'user_id':OWNER}])
def test_schedule_api_rejects_invalid_or_forged_inputs(body):
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:assert client.put('/api/v1/daily-reviews/schedule',params={'subject_id':SUBJECT},json=body).status_code==422
    finally:app.dependency_overrides.pop(get_current_user,None)


def test_schedule_and_history_use_authenticated_owner(monkeypatch):
    calls=[]
    monkeypatch.setattr(service,'save_schedule',lambda **values:calls.append(values) or {'version':1})
    monkeypatch.setattr(daily_review_service,'history',lambda **values:calls.append(values) or [])
    app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=OWNER)
    try:
        with TestClient(app) as client:
            assert client.put('/api/v1/daily-reviews/schedule',params={'subject_id':SUBJECT},json={'enabled':True,'hour':22,'version':0}).status_code==200
            assert calls[0]==dict(user_id=OWNER,subject_id=SUBJECT,enabled=True,hour=22,version=0)
            assert client.get('/api/v1/daily-reviews',params={'subject_id':SUBJECT,'before':'2026-10-22T10:00:00Z','before_id':JOB}).status_code==200
            assert calls[1]['before_id']==JOB and calls[1]['user_id']==OWNER
    finally:app.dependency_overrides.pop(get_current_user,None)
    with TestClient(app) as client:
        assert client.get('/api/v1/daily-reviews/schedule',params={'subject_id':SUBJECT}).status_code==401


def test_worker_and_beat_register_existing_learning_job_handlers():
    from app.worker.celery_app import celery_app
    from app.worker import tasks
    assert celery_app.conf.beat_schedule['dispatch-learning-jobs']['schedule']==60
    assert tasks.process_learning_job.name=='app.worker.tasks.process_learning_job'


def test_default_schedule_is_opt_in_and_latest_job_scoped(monkeypatch):
    filters=[]
    class Client:
        def table(self,name):filters.append(name);return self
        def select(self,*_):return self
        def eq(self,key,value):filters.append((key,value));return self
        def limit(self,*_):return self
        def order(self,*_,**__):return self
        def execute(self):return SimpleNamespace(data=[])
    monkeypatch.setattr(service,'get_supabase_client',lambda:Client())
    monkeypatch.setattr(service,'get_subject',lambda **_:None)
    assert service.schedule(user_id=OWNER,subject_id=SUBJECT)=={'enabled':False,'hour':22,'version':0,'timezone':'Asia/Shanghai','latestJob':None}
    assert filters.count(('user_id',OWNER))==2 and filters.count(('subject_id',SUBJECT))==2
