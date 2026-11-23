from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException
from app.config.settings import settings
from app.services import upload_cleanup_service as service


def test_scheduler_disabled_never_touches_storage(monkeypatch):
    monkeypatch.setattr(settings,'upload_cleanup_enabled',False)
    monkeypatch.setattr(service,'get_supabase_client',lambda:pytest.fail('side effect'))
    assert service.sweep()=={'status':'disabled'}


def test_preview_does_not_claim_or_delete(monkeypatch):
    def rpc(name,args):
        assert name=='ready_upload_cleanup'
        return NS(execute=lambda:NS(data=[{'id':'i','user_id':'owner'}]))
    monkeypatch.setattr(service,'get_supabase_client',lambda:NS(rpc=rpc))
    assert service.cleanup()['candidates']==1


@pytest.mark.parametrize('fault',['storage','unsafe','ack'])
def test_failure_keeps_recoverable_intent_and_never_leaks_provider_text(monkeypatch,fault):
    calls=[]
    row={'id':'i','user_id':'owner','bucket':settings.material_storage_bucket,
         'object_path':'owner/file','claim_token':'token'}
    if fault=='unsafe':row['object_path']='victim/file'
    def rpc(name,args):
        calls.append((name,args))
        if name=='ready_upload_cleanup':data=[row]
        elif name=='claim_upload_cleanup':data=row
        else:data=fault!='ack'
        return NS(execute=lambda:NS(data=data))
    def remove(paths):
        assert fault!='unsafe'
        if fault=='storage':raise TimeoutError('secret provider response')
    monkeypatch.setattr(service,'get_supabase_client',lambda:NS(rpc=rpc,storage=NS(from_=lambda _:NS(remove=remove))))
    result=service.cleanup(dry_run=False)
    assert result['removed']==0
    assert 'secret' not in str(calls)
    if fault!='ack':assert calls[-1][1]['p_error'] in ('ValueError','TimeoutError')


def test_busy_owner_leaves_intent_unclaimed(monkeypatch):
    def rpc(name,args):
        assert name=='ready_upload_cleanup'
        return NS(execute=lambda:NS(data=[{'id':'i','user_id':'owner'}]))
    @contextmanager
    def busy(_):raise HTTPException(409,'busy');yield
    monkeypatch.setattr(service,'get_supabase_client',lambda:NS(rpc=rpc))
    monkeypatch.setattr(service.owner_io_service,'hold_owner_io',busy)
    assert service.cleanup(dry_run=False)['skipped']==1
