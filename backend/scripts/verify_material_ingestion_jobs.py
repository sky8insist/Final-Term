"""Real local DB/Storage/Redis/solo Worker; explicitly fake embedding/graph.

Only disposable owners and a uniquely named queue. TXT parser is real; no paid
model, MinerU, ASR or LightRAG requests. SQL failure and lease expiry are injected.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import psycopg
from celery.contrib.testing.worker import start_worker
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import ingestion_service, material_ingestion_job_service as jobs, material_service
from app.services import privacy_service, retention_service, owner_io_service
from app.services.workspace_cache_service import get_redis_client
from app.worker.celery_app import celery_app
from app.worker.tasks import process_material


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT.parent/'docs/acceptance/material_ingestion_jobs_20261027/report.json')
    args=parser.parse_args()
    for value in (settings.database_url,settings.supabase_url,settings.redis_url):
        if urlparse(value or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local services only')
    os.environ['NO_PROXY']=os.environ['no_proxy']='localhost,127.0.0.1,::1'
    report={'startedAt':datetime.now(UTC).isoformat(),'checks':[],'cleanup':False,
      'scope':'synthetic private-service/real TXT/DB/Storage/Redis/solo worker',
      'providers':'fake deterministic 3D embedding and injected optional graph failure; no real model/graph requests',
      'limitations':['no browser/ordinary user JWT or real MinerU/ASR/model quality',
       'no sustained Beat/distributed fleet/P95','cooperating owner IO serialization; direct admin/legacy workers bypass it',
       'storage-before-registration orphan window and external graph atomicity remain']}
    owner,other,subject=uuid4(),uuid4(),uuid4();queue='acceptance.ingestion.'+uuid4().hex
    report['fixtureOwners']=[str(owner),str(other)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    client=get_supabase_client();results=[];paths=[];counts={'parse':0,'embed':0,'graph':0}
    saved=(material_service._parse_material_blocks,material_service.embed_texts,material_service.delete_material_index,
           material_service.index_material,jobs.optional_postprocessing,process_material.delay,celery_app.conf.task_always_eager)
    def passed(name):report['checks'].append({'name':name,'status':'passed'});print('PASS: '+name,flush=True)
    def parse(**kw):counts['parse']+=1;return saved[0](**kw)
    def embed(texts):counts['embed']+=1;return [[.1,.2,.3] for _ in texts]
    def graph(**kw):counts['graph']+=1;raise material_service.LightRAGServiceError('Explicit graph fault')
    def down(*a,**kw):raise ConnectionError('injected lost broker')
    material_service._parse_material_blocks=parse;material_service.embed_texts=embed
    material_service.delete_material_index=lambda **_:None;material_service.index_material=graph
    jobs.optional_postprocessing=lambda *_:{};process_material.delay=down
    celery_app.conf.task_always_eager=False
    with psycopg.connect(settings.database_url) as conn:
        try:
            if args.apply:
                conn.execute((ROOT/'migrations/060_material_ingestion_jobs.sql').read_text(encoding='utf-8'));conn.commit()
                print('Applied local migration 060',flush=True)
            if not conn.execute("select to_regclass('material_ingestion_checkpoints')").fetchone()[0]:raise RuntimeError('060 required')
            for uid in (owner,other):conn.execute('insert into auth.users(id) values(%s)',(uid,))
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Ingestion jobs fixture')",(subject,owner));conn.commit()
            def upload(suffix):
                data=('Atomic transaction and vector checkpoint fixture '+suffix).encode()
                file=UploadFile(BytesIO(data),filename='fixture.txt',headers=Headers({'content-type':'text/plain'}))
                result=ingestion_service.queue_upload(user_id=str(owner),subject_id=str(subject),file=file)
                asset=conn.execute('select object_path from material_assets where material_id=%s',(result['material']['id'],)).fetchone()[0]
                paths.append(asset);conn.commit();return result
            queued=upload('one');task=queued['task']['id'];mid=queued['material']['id']
            assert queued['task']['status']=='queued' and queued['task']['attempts']==0
            assert conn.execute('select error_code from processing_tasks where id=%s',(task,)).fetchone()[0]=='dispatch_pending'
            assert task in conn.execute('select ready_material_ingestions(50,%s)',(owner,)).fetchone()[0]
            conn.commit();passed('real upload atomically registers source/task; broker failure leaves durable queued task with zero attempts')
            # Reject publication after chunks/vectors have been written, proving
            # the complete canonical transaction rolls back, not just status.
            conn.execute("create function public.ingestion_fixture_failure() returns trigger language plpgsql as $$begin raise exception 'injected publication failure';end$$")
            conn.execute(f"create trigger ingestion_fixture_failure before update of status on processing_tasks for each row when(new.id='{task}' and new.status='succeeded') execute function public.ingestion_fixture_failure()")
            conn.commit()
            process_material.delay=lambda tid:process_material.apply_async(args=[tid],queue=queue)
            with start_worker(celery_app,pool='solo',queues=[queue],hostname=queue,perform_ping_check=False,shutdown_timeout=15,without_heartbeat=True):
                def dispatch(tid):
                    result=process_material.apply_async(args=[tid],queue=queue);results.append(result)
                    return result.get(timeout=45,disable_sync_subtasks=False)
                first=dispatch(task);assert first['status']=='retry_or_failed',first
                assert conn.execute('select count(*) from material_ingestion_checkpoints where task_id=%s',(task,)).fetchone()[0]==2
                assert conn.execute('select count(*) from content_blocks where material_id=%s',(mid,)).fetchone()[0]==0
                assert conn.execute('select count(*) from material_chunks where material_id=%s',(mid,)).fetchone()[0]==0
                assert conn.execute('select status from materials where id=%s',(mid,)).fetchone()[0]=='queued'
                assert counts['parse']==counts['embed']==1
                conn.execute('drop trigger ingestion_fixture_failure on processing_tasks');conn.execute('drop function ingestion_fixture_failure()')
                conn.execute("update processing_tasks set ingestion_available_at=now()-interval '1 second' where id=%s",(task,));conn.commit()
                passed('SQL publication fault rolls back blocks/chunks/vectors/ready while keeping both paid-stage checkpoints')
                second=dispatch(task);assert second['status']=='ready',second
                assert counts['parse']==counts['embed']==1 and counts['graph']==2,counts
                assert conn.execute('select count(*) from material_chunks where material_id=%s and embedding_dimensions=3',(mid,)).fetchone()[0]>0
                assert conn.execute('select count(*) from material_ingestion_checkpoints where task_id=%s',(task,)).fetchone()[0]==0
                assert conn.execute('select status from lightrag_material_index where material_id=%s',(mid,)).fetchone()[0]=='failed'
                assert conn.execute("select count(*) from learning_domain_events where user_id=%s and source_id=%s and event_type='material.indexed'",(owner,mid)).fetchone()[0]==1
                conn.commit();passed('retry resumes parsed+embedded snapshots without repeat calls; optional graph failure preserves vector/keyword readiness and one domain event')
                third=dispatch(task);assert third['status']=='skipped' and counts['embed']==1
                passed('duplicate completed delivery skips parsing, embedding and publication')
            # New queued job used only to test lease ownership and cancellation.
            process_material.delay=down
            queued2=upload('two');task2=queued2['task']['id'];mid2=queued2['material']['id']
            old=conn.execute('select claim_material_ingestion(%s)',(task2,)).fetchone()[0];conn.commit()
            assert conn.execute('select claim_material_ingestion(%s)',(task2,)).fetchone()[0] is None
            assert not conn.execute('select touch_material_ingestion(%s,%s)',(task2,uuid4())).fetchone()[0]
            conn.execute("update processing_tasks set ingestion_lease_until=now()-interval '1 second' where id=%s",(task2,));conn.commit()
            fresh=conn.execute('select claim_material_ingestion(%s)',(task2,)).fetchone()[0]
            assert fresh['ingestion_token']!=old['ingestion_token'] and fresh['attempts']==2
            assert not conn.execute('select touch_material_ingestion(%s,%s)',(task2,old['ingestion_token'])).fetchone()[0]
            conn.commit();passed('live lease rejects duplicate/wrong token; expiry issues new token without resetting attempts')
            conn.execute('select cancel_material_ingestion(%s,%s)',(owner,task2));conn.commit()
            try:
                with conn.transaction():conn.execute("select publish_material_ingestion(%s,%s,'version','failed','fixture')",(task2,fresh['ingestion_token']))
                raise AssertionError('Cancelled publication allowed')
            except psycopg.errors.SerializationFailure:pass
            assert not conn.execute("select fail_material_ingestion(%s,%s,'late error')",(task2,fresh['ingestion_token'])).fetchone()[0]
            assert conn.execute('select count(*) from content_blocks where material_id=%s',(mid2,)).fetchone()[0]==0
            conn.commit();passed('cancel atomically revokes claim; late publication/failure cannot change cancellation or create canonical blocks')
            try:
                with conn.transaction():conn.execute('select cancel_material_ingestion(%s,%s)',(other,task2))
                raise AssertionError('Foreign cancellation allowed')
            except psycopg.errors.InsufficientPrivilege:pass
            assert not conn.execute("select has_function_privilege('authenticated','publish_material_ingestion(uuid,uuid,text,text,text)','execute')").fetchone()[0]
            conn.commit();passed('foreign owner and direct authenticated publication denied')
            # A real second thread has a fresh context, like an independent API.
            with owner_io_service.hold_owner_io(str(owner)):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    try:pool.submit(privacy_service.delete_learning_data,user_id=str(owner)).result()
                    except HTTPException as exc:assert exc.status_code==409
                    else:raise AssertionError('Privacy deletion entered active ingestion IO')
                    assert pool.submit(jobs.run,task2).result()['status']=='busy'
                assert conn.execute('select exists(select 1 from materials where id=%s)',(mid,)).fetchone()[0]
            conn.commit();passed('actual independent thread receives busy for privacy deletion and worker claim while owner IO lock is held')
            # An expired file can be claimed before a writer takes the IO lock;
            # cleanup must still refuse the external operation under that lock.
            conn.execute("update material_assets set expires_at=now()-interval '1 day' where material_id=%s",(mid,));conn.commit()
            with owner_io_service.hold_owner_io(str(owner)):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    cleanup=pool.submit(retention_service.cleanup_assets,user_id=str(owner)).result()
                    assert cleanup['removed']==0 and cleanup['skipped']>=1,cleanup
            assert client.storage.from_(settings.material_storage_bucket).download(paths[0])
            passed('retention cleaner shares owner IO lock and leaves actual Storage object untouched during protected IO')
            bundle=conn.execute('select export_privacy_bundle(%s)',(owner,)).fetchone()[0]
            assert 'material_ingestion_checkpoints' in bundle['data']
            conn.commit()
            # Avoid real optional graph cleanup: this acceptance graph is fake.
            conn.execute('delete from lightrag_material_index where user_id=%s',(owner,));conn.commit()
            privacy_service.delete_learning_data(user_id=str(owner))
            assert conn.execute('select count(*) from processing_tasks where user_id=%s',(owner,)).fetchone()[0]==0
            passed('private export knows checkpoints; normal privacy cleanup removes tasks/checkpoints after IO completes')
            report['providerCallCounts']=counts
        except Exception as exc:report['failureType']=type(exc).__name__;raise
        finally:
            (material_service._parse_material_blocks,material_service.embed_texts,material_service.delete_material_index,
             material_service.index_material,jobs.optional_postprocessing,process_material.delay,celery_app.conf.task_always_eager)=saved
            conn.rollback()
            conn.execute('drop trigger if exists ingestion_fixture_failure on processing_tasks');conn.execute('drop function if exists ingestion_fixture_failure()')
            conn.commit()  # Never hold table DDL locks across external cleanup.
            if paths:
                try:client.storage.from_(settings.material_storage_bucket).remove(paths)
                except Exception as exc:report['cleanupStorageFailure']=type(exc).__name__
            for uid in (owner,other):
                conn.execute('delete from auth.users where id=%s',(uid,))
                redis=get_redis_client()
                for ns in ('v1','v2'):
                    keys=list(redis.scan_iter(match=f'workspace:{ns}:{uid}:*'))
                    if keys:redis.delete(*keys)
            conn.commit()
            for result in results:result.forget()
            if results:
                with celery_app.connection_for_write() as connection:connection.default_channel.queue_delete(queue=queue)
            report['cleanup']='cleanupStorageFailure' not in report and all(not conn.execute('select exists(select 1 from auth.users where id=%s)',(u,)).fetchone()[0] for u in (owner,other))
            report['success']='failureType' not in report and len(report['checks'])==10 and report['cleanup']
            report['finishedAt']=datetime.now(UTC).isoformat()
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Report saved; disposable owners/files/queue/results cleaned',flush=True)


if __name__=='__main__':main()
