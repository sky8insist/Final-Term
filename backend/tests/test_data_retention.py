from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from app.config.settings import Settings, settings
from app.services import retention_service as service


@pytest.mark.parametrize('field,value', [('retention_audit_days',90), ('retention_metric_days',0),
    ('retention_event_days',119), ('retention_batch_size',1001), ('retention_asset_batch_size',101)])
def test_unsafe_policy_is_rejected(field, value):
    with pytest.raises(ValidationError): Settings(**{field: value}, _env_file=None)


def test_disabled_scheduler_has_no_database_or_storage_effect(monkeypatch):
    monkeypatch.setattr(settings, 'data_retention_enabled', False)
    monkeypatch.setattr(service, 'get_supabase_client', lambda: pytest.fail('Unexpected destructive access'))
    assert service.sweep() == {'status': 'disabled'}


@pytest.mark.parametrize('fault', ['storage','ack','lease','renewed','none'])
def test_external_cleanup_failure_keeps_retry_path_and_rejects_old_claim(monkeypatch, fault):
    calls = []
    assets = [{'id':'asset','cleanup_token':'claim','bucket':settings.material_storage_bucket,
               'user_id':'owner','object_path':'owner/private-path'}]
    def rpc(name, args):
        calls.append((name,args))
        if name == 'claim_expired_assets': data=assets
        elif name == 'check_asset_cleanup': data=fault!='lease'
        elif name == 'finish_asset_cleanup':
            if fault == 'ack': raise RuntimeError('Database offline')
            data=fault!='renewed'
        else: pytest.fail(name)
        return NS(execute=lambda:NS(data=data))
    def remove(paths):
        calls.append(('storage',paths))
        if fault=='storage': raise TimeoutError('private URL and secret')
    monkeypatch.setattr(service,'get_supabase_client',lambda:NS(rpc=rpc,storage=NS(from_=lambda _:NS(remove=remove))))
    if fault=='ack':
        with pytest.raises(RuntimeError): service.cleanup_assets(user_id='owner')
    else:
        result=service.cleanup_assets(user_id='owner')
        assert result['removed'] == int(fault=='none')
        assert result['failed'] == int(fault=='storage')
    if fault=='lease': assert not any(name=='storage' for name,_ in calls)
    if fault=='storage':
        finished=[args for name,args in calls if name=='finish_asset_cleanup']
        assert finished == [{'p_asset':'asset','p_token':'claim','p_error':'TimeoutError'}]


def test_preview_does_not_request_deletion(monkeypatch):
    calls=[]
    def rpc(name,args):
        calls.append((name,args));return NS(execute=lambda:NS(data={'dryRun':True}))
    monkeypatch.setattr(service,'get_supabase_client',lambda:NS(rpc=rpc))
    assert service.prune(user_id='owner')['dryRun']
    assert calls[0][1]['p_dry_run'] is True and calls[0][1]['p_user']=='owner'


@pytest.mark.parametrize('bucket,path', [('other-bucket','owner/file'),
    (None,'victim/file'), (None,'owner/../victim/file')])
def test_unsafe_storage_target_is_retained_without_external_delete(monkeypatch,bucket,path):
    calls=[]
    row={'id':'id','cleanup_token':'token','user_id':'owner',
         'bucket':bucket or settings.material_storage_bucket,'object_path':path}
    def rpc(name,args):
        calls.append((name,args))
        return NS(execute=lambda:NS(data=[row] if name=='claim_expired_assets' else True))
    fake=NS(rpc=rpc,storage=NS(from_=lambda _:pytest.fail('Unsafe storage access')))
    monkeypatch.setattr(service,'get_supabase_client',lambda:fake)
    assert service.cleanup_assets()['failed']==1
    assert calls[-1][1]['p_error']=='UnsafeAssetPath'
