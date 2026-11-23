from contextlib import contextmanager
from types import SimpleNamespace as NS

from fastapi import HTTPException
import pytest

from app.config.settings import settings
from app.services import material_ingestion_job_service as jobs, owner_io_service
from app.services.owner_io_service import hold_owner_io as real_hold_owner_io


def test_checkpoint_identity_changes_with_source_or_pipeline(monkeypatch):
    first=jobs.pipeline_version('one')
    assert jobs.pipeline_version('two')!=first
    monkeypatch.setattr(settings,'embedding_model','different-model')
    assert jobs.pipeline_version('one')!=first


@pytest.mark.parametrize('claim', [None, {'id':'job','ingestion_token':'token','user_id':'owner'}])
def test_duplicate_claim_and_lost_lease_cannot_report_failure(monkeypatch,claim):
    from app.services.observability_service import user_id_context
    previous=user_id_context.get()
    class Q:
        def select(self,*a):return self
        def eq(self,*a):return self
        def limit(self,*a):return self
        def execute(self):return NS(data=[{'user_id':'owner'}])
    monkeypatch.setattr(jobs,'get_supabase_client',lambda:NS(table=lambda _:Q()))
    calls=[]
    def rpc(name,args):calls.append(name);return claim
    monkeypatch.setattr(jobs,'rpc',rpc)
    def lost(*a):
        assert user_id_context.get()=='owner'
        raise jobs.LeaseLost('cancelled')
    monkeypatch.setattr(jobs,'execute',lost)
    assert jobs.run('job')['status']==('skipped' if claim is None else 'lease_lost')
    assert calls==['claim_material_ingestion']
    assert user_id_context.get()==previous


def test_durable_sweep_keeps_failed_broker_deliveries_for_next_scan(monkeypatch):
    from app.worker.tasks import process_material
    monkeypatch.setattr(jobs,'rpc',lambda *a:['a','b'])
    def down(_):raise ConnectionError('secret broker URL')
    monkeypatch.setattr(process_material,'delay',down)
    assert jobs.sweep(user_id='owner')=={'dispatched':0,'dispatchFailed':2}


def test_heartbeat_refuses_expired_or_cancelled_claim(monkeypatch):
    monkeypatch.setattr(jobs,'rpc',lambda *a:False)
    with jobs.lease({'id':'id','ingestion_token':'token'}) as touch:
        with pytest.raises(jobs.LeaseLost):touch('embedding')


def test_nonblocking_owner_guard_rejects_competing_io(monkeypatch):
    class Conn:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,*a):return NS(fetchone=lambda:[False])
        def close(self):pass
    monkeypatch.setattr(owner_io_service.psycopg,'connect',lambda *a,**kw:Conn())
    with pytest.raises(HTTPException) as error:
        with real_hold_owner_io('00000000-0000-0000-0000-000000000001'):pytest.fail('lock acquired')
    assert error.value.status_code==409


def test_nested_owner_guard_shares_one_connection(monkeypatch):
    calls=[]
    class Conn:
        def __enter__(self):return self
        def __exit__(self,*a):calls.append('closed')
        def execute(self,*a):return NS(fetchone=lambda:[True])
        def close(self):calls.append('closed')
    def connect(*a,**kw):calls.append('open');return Conn()
    monkeypatch.setattr(owner_io_service.psycopg,'connect',connect)
    owner='00000000-0000-0000-0000-000000000001'
    with real_hold_owner_io(owner) as first:
        with real_hold_owner_io(owner) as second:assert first is second
    assert calls==['open','closed']


def test_busy_io_does_not_claim_or_increment_attempts(monkeypatch):
    class Q:
        def select(self,*a):return self
        def eq(self,*a):return self
        def limit(self,*a):return self
        def execute(self):return NS(data=[{'user_id':'owner'}])
    monkeypatch.setattr(jobs,'get_supabase_client',lambda:NS(table=lambda _:Q()))
    @contextmanager
    def busy(_):raise HTTPException(409,'busy');yield
    monkeypatch.setattr(owner_io_service,'hold_owner_io',busy)
    monkeypatch.setattr(jobs,'rpc',lambda *a:pytest.fail('claimed while IO is busy'))
    assert jobs.run('job')=={'status':'busy'}
