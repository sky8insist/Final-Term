"""Bounded local SQL/Storage/real owner-lock verification, no model calls."""
import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Event
import time
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import psycopg
from fastapi import HTTPException
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import upload_cleanup_service as cleanup, lightrag_service as graph
from app.services import privacy_service, subject_service, owner_io_service
from app.services.workspace_cache_service import get_redis_client


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT.parent/'docs/acceptance/upload_recovery_20261123/report.json')
    args=parser.parse_args()
    for value in (settings.database_url,settings.supabase_url,settings.redis_url):
        if urlparse(value or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local services required')
    os.environ['NO_PROXY']=os.environ['no_proxy']='localhost,127.0.0.1,::1'
    owner,other=str(uuid4()),str(uuid4());paths=[]
    report={'startedAt':datetime.now(UTC).isoformat(),'owners':[owner,other],'checks':[],
            'scope':'local SQL/Storage/real PostgreSQL owner lock; injected graph coroutine, no model/ASR/graph provider',
            'limitations':['no continuous Beat or multi-host fault injection','no historical unrecorded-object scan','uncancellable providers can keep owner busy until they finish']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    client=get_supabase_client();release=Event();original=(graph._index_material_async,settings.lightrag_index_timeout_seconds,cleanup.get_supabase_client)
    def passed(name):report['checks'].append({'name':name,'status':'passed'});print('PASS: '+name,flush=True)
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        def seed(tag,old=True):
            subject,material=str(uuid4()),str(uuid4());blob=('recovery-'+tag).encode();digest=hashlib.sha256(blob).hexdigest()
            path=f'{owner}/{subject}/{material}/source.txt'
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Upload recovery fixture')",(subject,owner))
            conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status,source_hash) values(%s,%s,%s,'source.txt','text/plain',%s,'queued',%s)",(material,owner,subject,len(blob),digest));conn.commit()
            intent=client.rpc('prepare_material_upload',{'p_user':owner,'p_material':material,'p_bucket':settings.material_storage_bucket,'p_path':path,'p_hash':digest}).execute().data
            paths.append(path);client.storage.from_(settings.material_storage_bucket).upload(path,blob,{'content-type':'text/plain'})
            if old:conn.execute("update material_upload_intents set created_at=now()-interval '2 hours' where id=%s",(intent,));conn.commit()
            return {'id':intent,'material':material,'subject':subject,'path':path,'hash':digest,'blob':blob}
        def register(item,attempts=3):
            return client.rpc('register_material_upload',{'p_user':owner,'p_material':item['material'],
             'p_asset':{'bucket':settings.material_storage_bucket,'object_path':item['path'],'sha256':item['hash'],'expires_at':None},'p_metadata':{},'p_attempts':attempts}).execute().data
        try:
            for uid in (owner,other):conn.execute('insert into auth.users(id) values(%s)',(uid,))
            conn.commit()
            orphan=seed('orphan');fresh=seed('fresh',False)
            preview=cleanup.cleanup(user_id=owner);assert preview['candidates']==1 and preview['removed']==0
            assert client.storage.from_(settings.material_storage_bucket).download(orphan['path'])==orphan['blob']
            passed('recorded orphan preview is read-only and respects grace period')
            result=cleanup.cleanup(user_id=owner,dry_run=False);assert result['removed']==1,result
            assert conn.execute('select status from material_upload_intents where id=%s',(orphan['id'],)).fetchone()[0]=='cleaned'
            assert conn.execute('select status from materials where id=%s',(orphan['material'],)).fetchone()[0]=='failed'
            conn.commit();passed('abandoned object removed with durable completion and failed-material recovery state')
            registered=seed('registered');job=register(registered)
            conn.execute("update processing_tasks set ingestion_available_at=now()+interval '1 day' where id=%s",(job['id'],));conn.commit()
            assert cleanup.cleanup(user_id=owner,dry_run=False)['removed']==0
            assert client.storage.from_(settings.material_storage_bucket).download(registered['path'])==registered['blob']
            passed('registered manifest/task destination is excluded from orphan deletion')
            # Simulate an old/ambiguous acknowledgement: manifest is authoritative.
            conn.execute("update material_upload_intents set status='pending' where id=%s",(registered['id'],));conn.commit()
            assert cleanup.cleanup(user_id=owner,dry_run=False)['skipped']==1
            assert conn.execute('select status from material_upload_intents where id=%s',(registered['id'],)).fetchone()[0]=='registered'
            conn.commit();passed('manifest reconciliation protects files after lost registration acknowledgement')
            failed=seed('failed-registration')
            try:register(failed,0)
            except Exception:pass
            else:raise AssertionError('Invalid registration accepted')
            assert conn.execute('select count(*) from material_assets where material_id=%s',(failed['material'],)).fetchone()[0]==0
            assert conn.execute('select count(*) from processing_tasks where material_id=%s',(failed['material'],)).fetchone()[0]==0
            conn.commit();assert cleanup.cleanup(user_id=owner,dry_run=False)['removed']==1
            passed('registration failure rolls back manifest/task and leaves original intent available for cleanup')
            retry=seed('retry')
            def down(_):raise TimeoutError('injected provider text must not persist')
            cleanup.get_supabase_client=lambda:SimpleNamespace(rpc=client.rpc,storage=SimpleNamespace(from_=lambda _:SimpleNamespace(remove=down)))
            result=cleanup.cleanup(user_id=owner,dry_run=False);assert result['failed']==1
            cleanup.get_supabase_client=original[2]
            error,retry_future=conn.execute('select error_code,retry_at>now() from material_upload_intents where id=%s',(retry['id'],)).fetchone()
            assert error=='TimeoutError' and retry_future
            conn.execute("update material_upload_intents set retry_at=now()-interval '1 second' where id=%s",(retry['id'],));conn.commit()
            assert cleanup.cleanup(user_id=owner,dry_run=False)['removed']==1
            passed('Storage fault retains intent with sanitized error and backoff; retry is idempotent')
            assert not conn.execute('select finish_upload_cleanup(%s,%s)',(fresh['id'],uuid4())).fetchone()[0]
            assert not conn.execute("select has_function_privilege('authenticated','prepare_material_upload(uuid,uuid,text,text,text)','execute')").fetchone()[0]
            assert cleanup.cleanup(user_id=other)['candidates']==0
            conn.commit();passed('stale token and authenticated direct write denied; another owner has no candidates')
            entered=Event()
            async def stuck(**kw):entered.set();release.wait(3);return 'injected-workspace'
            graph._index_material_async=stuck;settings.lightrag_index_timeout_seconds=.02
            with owner_io_service.hold_owner_io(owner) as io:
                try:graph.index_material(user_id=owner,subject_id=fresh['subject'],material_id=fresh['material'],filename='source.txt',chunks=[],embedding_dimension=3)
                except graph.LightRAGServiceError:pass
                else:raise AssertionError('Expected graph timeout')
            assert entered.is_set() and not io.closed
            try:privacy_service.delete_learning_data(user_id=owner)
            except HTTPException as exc:assert exc.status_code==409
            else:raise AssertionError('Owner lock released before background IO finished')
            release.set()
            for _ in range(100):
                if io.closed:break
                time.sleep(.01)
            assert io.closed
            passed('real PostgreSQL lock stays held after graph timeout until uncancellable background IO actually ends')
            async def cooperative(**kw):await asyncio.sleep(1);raise AssertionError('Late write')
            graph._index_material_async=cooperative
            with owner_io_service.hold_owner_io(owner) as io:
                try:graph.index_material(user_id=owner,subject_id=fresh['subject'],material_id=fresh['material'],filename='source.txt',chunks=[],embedding_dimension=3)
                except graph.LightRAGServiceError:pass
            assert io.closed
            graph._index_material_async=original[0];settings.lightrag_index_timeout_seconds=original[1]
            passed('cooperative graph timeout cancels work and releases the real owner transaction')
            subject_orphan=seed('subject-delete',False)
            subject_service.delete_subject(user_id=owner,subject_id=subject_orphan['subject'])
            assert conn.execute('select material_id from material_upload_intents where id=%s',(subject_orphan['id'],)).fetchone()[0] is None
            conn.commit()
            bundle=privacy_service.export_user_data(user_id=owner)
            assert 'material_upload_intents' in bundle['data']
            privacy_service.delete_learning_data(user_id=owner)
            assert conn.execute('select count(*) from material_upload_intents where user_id=%s',(owner,)).fetchone()[0]==0
            passed('subject and privacy deletion include pending destinations; export includes intents')
        except Exception as exc:report['failureType']=type(exc).__name__;raise
        finally:
            release.set();graph._index_material_async,settings.lightrag_index_timeout_seconds,cleanup.get_supabase_client=original
            conn.rollback();conn.commit()
            try:
                if paths:client.storage.from_(settings.material_storage_bucket).remove(paths)
            except Exception as exc:report['cleanupStorageFailure']=type(exc).__name__
            for uid in (owner,other):
                conn.execute('delete from auth.users where id=%s',(uid,))
                redis=get_redis_client()
                for ns in ('v1','v2'):
                    keys=list(redis.scan_iter(match=f'workspace:{ns}:{uid}:*'))
                    if keys:redis.delete(*keys)
            conn.commit()
            report['cleanup']='cleanupStorageFailure' not in report and all(not conn.execute('select exists(select 1 from auth.users where id=%s)',(u,)).fetchone()[0] for u in (owner,other))
            report['success']='failureType' not in report and len(report['checks'])==10 and report['cleanup']
            report['finishedAt']=datetime.now(UTC).isoformat()
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Report saved; exact fixture identities and objects cleaned',flush=True)


if __name__=='__main__':main()
