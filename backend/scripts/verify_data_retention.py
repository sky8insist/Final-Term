"""Local disposable SQL/Storage/Redis/isolated Celery retention acceptance."""
import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg
from psycopg.types.json import Jsonb
from celery.contrib.testing.worker import start_worker
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services.workspace_cache_service import get_redis_client
from app.worker.celery_app import celery_app
from app.worker.tasks import cleanup_expired_assets

FAMILIES = ('product_events','recommendation_audits','learning_metric_cohorts',
            'mastery_prediction_samples','mastery_prediction_coverage','learning_domain_events')


def seed(conn, owner):
    subject = uuid4()
    conn.execute('insert into auth.users(id) values(%s)', (owner,))
    conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Retention fixture')", (subject,owner))
    for _ in range(3):
        conn.execute("insert into recommendation_audits(id,user_id,subject_id,algorithm_version,snapshot,created_at) values(%s,%s,%s,'fixture','{}',now()-interval '200 days')", (uuid4(),owner,subject))
        conn.execute("insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version,created_at) values(%s,%s,'step.completed','study_session_steps',%s,'1','fixture',now()-interval '200 days')", (owner,subject,uuid4()))
        conn.execute("insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline) values(%s,%s,'guided_session',%s,'1','fixture',now()-interval '410 days',now()-interval '403 days')", (owner,subject,uuid4()))
        conn.execute("insert into mastery_prediction_samples(id,user_id,subject_id,attempt_id,question_id,prediction,actual,released_at) values(%s,%s,%s,%s,%s,'{\"score\":0.5}',true,now()-interval '400 days')", (uuid4(),owner,subject,uuid4(),uuid4()))
        conn.execute("insert into mastery_prediction_coverage(id,user_id,subject_id,known_outcome,has_prediction,reason,released_at) values(%s,%s,%s,true,true,'available',now()-interval '400 days')", (uuid4(),owner,subject))
        conn.execute("insert into learning_domain_events(user_id,subject_id,event_type,source_table,source_id,revision,occurred_at,consumed_at) values(%s,%s,'task.missed','review_tasks',%s,'2020-01-01',now()-interval '200 days',now()-interval '199 days')", (owner,subject,uuid4()))
    conn.execute("update learning_job_outbox set status='succeeded' where user_id=%s", (owner,))
    conn.execute("insert into learning_domain_events(user_id,subject_id,event_type,source_table,source_id,revision,occurred_at) values(%s,%s,'task.missed','review_tasks',%s,'2020-01-01',now()-interval '200 days')", (owner,subject,uuid4()))
    conn.execute("insert into learning_domain_events(user_id,subject_id,event_type,source_table,source_id,revision,occurred_at,consumed_at) values(%s,%s,'task.missed','review_tasks',%s,'2020-01-01',now()-interval '200 days',now())", (owner,subject,uuid4()))
    conn.execute("update learning_job_outbox set status='dead' where user_id=%s and status='queued'", (owner,))
    # Recent data must survive even if another family is eligible.
    conn.execute("insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version) values(%s,%s,'step.completed','fixture',%s,'1','fixture')", (owner,subject,uuid4()))
    conn.commit()
    return subject


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT.parent/'docs/acceptance/data_retention_20261027/report.json')
    args=parser.parse_args()
    for value in (settings.database_url,settings.supabase_url,settings.redis_url):
        if urlparse(value or '').hostname not in {'localhost','127.0.0.1','::1'}: raise SystemExit('Local services only')
    os.environ['NO_PROXY']=os.environ['no_proxy']='localhost,127.0.0.1,::1'
    owner,other=uuid4(),uuid4()
    queue='acceptance.retention.'+uuid4().hex
    report={'startedAt':datetime.now(UTC).isoformat(),'scope':'local synthetic SQL/Storage/Redis/isolated solo worker',
            'checks':[],'cleanup':False,'limitations':['no sustained Beat/distributed fleet/production acceptance',
             'no cross-service upload/deletion publication fence','no model/ASR/browser/LightRAG call',
             'receipt and completed-job identities remain until subject/account deletion']}
    client=get_supabase_client();paths=[];results=[]
    original_eager=celery_app.conf.task_always_eager
    original=(settings.data_retention_enabled,settings.retention_batch_size,settings.retention_asset_batch_size)
    def passed(name):
        report['checks'].append({'name':name,'status':'passed'});print('PASS: '+name,flush=True)
    with psycopg.connect(settings.database_url) as conn:
        def prune(dry=True):
            return conn.execute('select prune_retained_data(180,365,180,2,%s,%s)',(dry,owner)).fetchone()[0]
        def asset(material_status='ready',expires="now()-interval '1 day'"):
            material,asset_id=uuid4(),uuid4()
            path=f'{owner}/{subject}/{material}/fixture.wav'
            client.storage.from_(settings.material_storage_bucket).upload(path,b'retention-fixture',{'content-type':'application/octet-stream'})
            paths.append(path)
            conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'fixture.wav','audio/wav',17,%s)",(material,owner,subject,material_status))
            conn.execute(f"insert into material_assets(id,user_id,subject_id,material_id,bucket,object_path,content_type,file_size,sha256,expires_at) values(%s,%s,%s,%s,%s,%s,'audio/wav',17,%s,{expires})",(asset_id,owner,subject,material,settings.material_storage_bucket,path,hashlib.sha256(b'retention-fixture').hexdigest()))
            return asset_id,material,path
        try:
            if args.apply:
                conn.execute((ROOT/'migrations/059_data_retention.sql').read_text(encoding='utf-8'));conn.commit()
                print('Applied local migration 059',flush=True)
            if not conn.execute("select to_regclass('retention_receipts')").fetchone()[0]:raise RuntimeError('059 required')
            subject=seed(conn,owner);seed(conn,other)
            before={}
            for table in FAMILIES:
                guard=" and created_at<now()-interval '180 days'" if table in ('product_events','recommendation_audits') else ''
                if table=='learning_domain_events':
                    guard=" and consumed_at is not null and not exists(select 1 from learning_job_outbox j where j.source_id=t.id and j.status<>'succeeded')"
                before[table]=conn.execute(f'select to_jsonb(t) from {table} t where user_id=%s {guard} order by id limit 1',(owner,)).fetchone()[0]
            preview=prune();conn.commit()
            assert all(n==2 for n in preview['counts'].values()),preview
            assert conn.execute('select count(*) from retention_receipts where user_id=%s',(owner,)).fetchone()[0]==0
            passed('dry-run shows bounded candidates in all six families without deleting or writing receipts')
            try:
                conn.execute("create function public.retention_fixture_failure() returns trigger language plpgsql as $$begin raise exception 'injected retention failure';end$$")
                conn.execute(f"create trigger retention_fixture_failure before delete on product_events for each row when(old.user_id='{owner}') execute function public.retention_fixture_failure()")
                try:
                    with conn.transaction(): prune(False)
                    raise AssertionError('Expected injected failure')
                except psycopg.errors.RaiseException: pass
                assert conn.execute('select count(*) from retention_receipts where user_id=%s',(owner,)).fetchone()[0]==0
            finally: conn.rollback()
            passed('injected delete failure rolls back purge and fingerprint receipts together')
            first=prune(False);conn.commit()
            assert all(n==2 for n in first['counts'].values())
            assert conn.execute('select count(*) from retention_receipts where user_id=%s',(owner,)).fetchone()[0]==12
            second=prune(False);conn.commit();assert all(n==1 for n in second['counts'].values())
            assert all(n==0 for n in prune(False)['counts'].values());conn.commit()
            assert conn.execute('select count(*) from product_events where user_id=%s',(owner,)).fetchone()[0]==1
            assert conn.execute('select count(*) from learning_domain_events where user_id=%s',(owner,)).fetchone()[0]==2
            assert conn.execute('select count(*) from product_events where user_id=%s',(other,)).fetchone()[0]==4
            passed('bounded repeated purge drains old data; recent/other-owner/unconsumed/dead-job events survive')
            jobs=conn.execute('select count(*) from learning_job_outbox where user_id=%s',(owner,)).fetchone()[0]
            for table,row in before.items():
                # Replay with fresh UUIDs for records deduped by their source key.
                if table in ('product_events','learning_metric_cohorts','learning_domain_events'):row['id']=str(uuid4())
                inserted=conn.execute(f'insert into {table} select (jsonb_populate_record(null::{table},%s)).* returning id',(Jsonb(row),)).fetchall()
                assert not inserted,(table,inserted)
            assert conn.execute('select count(*) from learning_job_outbox where user_id=%s',(owner,)).fetchone()[0]==jobs
            conn.commit()
            passed('all six purged-source replays are suppressed, including fresh-ID events and outbox resurrection')
            topic,session=uuid4(),uuid4()
            step=before['product_events']['source_id']
            conn.execute("insert into knowledge_points(id,user_id,subject_id,knowledge_key,title) values(%s,%s,%s,'retention','Fixture')",(topic,owner,subject))
            conn.execute("insert into study_sessions(id,user_id,subject_id,knowledge_point_id,goal,minutes,context) values(%s,%s,%s,%s,'fixture',10,'{\"algorithmVersion\":\"fixture\"}')",(session,owner,subject,topic))
            conn.execute("insert into study_session_steps(id,session_id,user_id,subject_id,sequence_index,kind,title,estimated_minutes,status,output) values(%s,%s,%s,%s,0,'quiz','fixture',5,'completed','{\"scoreRatio\":0.2}')",(step,session,owner,subject))
            assert conn.execute("select count(*) from learning_metric_cohorts where user_id=%s and kind='quiz_remediation'",(owner,)).fetchone()[0]==0
            conn.commit();passed('restoring a previously completed low-score step cannot create a fresh remediation cohort after event purge')
            bundle=conn.execute('select export_privacy_bundle(%s)',(owner,)).fetchone()[0]
            assert len(bundle['data']['retention_receipts'])==18
            assert not conn.execute("select has_table_privilege('authenticated','retention_receipts','select')").fetchone()[0]
            assert not conn.execute("select has_function_privilege('anon','prune_retained_data(integer,integer,integer,integer,boolean,uuid)','execute')").fetchone()[0]
            conn.commit();passed('receipts included in private export; anonymous purge and direct authenticated receipt reads denied')
            a,_,pa=asset();b,_,pb=asset();future,_,pf=asset(expires="now()+interval '1 day'")
            busy,material_busy,pbusy=asset('failed')
            conn.execute("insert into processing_tasks(user_id,subject_id,material_id,idempotency_key) values(%s,%s,%s,%s)",(owner,subject,material_busy,str(uuid4())))
            conn.commit()
            claim=conn.execute('select claim_expired_assets(1,%s)',(owner,)).fetchone()[0][0]
            with psycopg.connect(settings.database_url) as parallel:
                next_claim=parallel.execute('select claim_expired_assets(1,%s)',(owner,)).fetchone()[0][0]
                assert next_claim['id']!=claim['id'];parallel.rollback()
            conn.commit()
            assert not conn.execute('select finish_asset_cleanup(%s,%s)',(claim['id'],uuid4())).fetchone()[0]
            passed('two actual database connections claim disjoint assets with SKIP LOCKED; wrong token rejected')
            conn.execute("update material_assets set expires_at=now()+interval '1 day' where id=%s",(claim['id'],))
            assert not conn.execute('select check_asset_cleanup(%s,%s)',(claim['id'],claim['cleanup_token'])).fetchone()[0]
            assert not conn.execute('select finish_asset_cleanup(%s,%s)',(claim['id'],claim['cleanup_token'])).fetchone()[0]
            conn.execute('update material_assets set expires_at=cleanup_expected_expiry where id=%s',(claim['id'],))
            other_claim=conn.execute('select claim_expired_assets(1,%s)',(owner,)).fetchone()[0][0]
            conn.execute("select finish_asset_cleanup(%s,%s,'TimeoutError')",(other_claim['id'],other_claim['cleanup_token']))
            assert conn.execute('select preview_expired_assets(100,%s)',(owner,)).fetchone()[0]==0
            assert conn.execute('select cleanup_retry_at>now() from material_assets where id=%s',(other_claim['id'],)).fetchone()[0]
            conn.commit();passed('renewed manifest protected; failed cleanup retains manifest with backoff; active lease/future/busy assets excluded')
            # Real Storage delete followed by a simulated lost DB ack/crashed cleaner.
            client.storage.from_(claim['bucket']).remove([claim['object_path']])
            conn.execute("update material_assets set cleanup_lease_until=now()-interval '1 second' where id=%s",(claim['id'],));conn.commit()
            celery_app.conf.task_always_eager=False
            settings.data_retention_enabled=True;settings.retention_batch_size=2;settings.retention_asset_batch_size=1
            with start_worker(celery_app,pool='solo',queues=[queue],hostname=queue,perform_ping_check=False,shutdown_timeout=15,without_heartbeat=True):
                def dispatch():
                    result=cleanup_expired_assets.apply_async(kwargs={'user_id':str(owner)},queue=queue);results.append(result)
                    return result.get(timeout=30,disable_sync_subtasks=False)
                one=dispatch();assert one['assets']['removed']==1,one
                conn.execute("update material_assets set cleanup_retry_at=now()-interval '1 second' where id=%s",(other_claim['id'],));conn.commit()
                two=dispatch();assert two['assets']['removed']==1,two
                three=dispatch();assert three['assets']['claimed']==0,three
                report['workerResults']=[one,two,three]
            assert conn.execute('select count(*) from material_assets where id=any(%s)',([a,b],)).fetchone()[0]==0
            assert client.storage.from_(settings.material_storage_bucket).download(pf)==b'retention-fixture'
            assert client.storage.from_(settings.material_storage_bucket).download(pbusy)==b'retention-fixture'
            assert conn.execute('select count(*) from material_assets where id=any(%s)',([future,busy],)).fetchone()[0]==2
            conn.commit();passed('real isolated Redis/solo worker recovers deleted-file lost-ack, retries failure and safely repeats; busy/future files remain')
            conn.execute('select delete_privacy_learning_data(%s)',(owner,));conn.commit()
            assert conn.execute('select count(*) from retention_receipts where user_id=%s',(owner,)).fetchone()[0]==0
            passed('normal privacy transaction also erases all retained dedupe receipts')
        except Exception as exc:
            report['failureType']=type(exc).__name__;raise
        finally:
            settings.data_retention_enabled,settings.retention_batch_size,settings.retention_asset_batch_size=original
            celery_app.conf.task_always_eager=original_eager
            conn.rollback()
            if paths:client.storage.from_(settings.material_storage_bucket).remove(paths)
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
            report['cleanup']=all(not conn.execute('select exists(select 1 from auth.users where id=%s)',(u,)).fetchone()[0] for u in (owner,other))
            report['success']='failureType' not in report and len(report['checks'])==10 and report['cleanup']
            report['finishedAt']=datetime.now(UTC).isoformat()
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Report saved; exact disposable users/files/queue/results cleaned',flush=True)


if __name__=='__main__':main()
