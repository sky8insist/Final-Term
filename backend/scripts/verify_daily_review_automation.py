"""Local automation acceptance; fixture/job writes roll back, no broker/model calls."""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings
from app.services.daily_review_service import build_learning_review_graph


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--api',action='store_true');args=parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local DB required')
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        migration=(Path(__file__).resolve().parents[1]/'migrations/052_daily_review_automation.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.daily_review_schedules')").fetchone()[0]:
            if not args.apply:raise SystemExit('Missing 052; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 052')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;',migration,re.S):conn.execute(sql.replace('create function','create or replace function',1))
            conn.execute("notify pgrst,'reload schema'");conn.commit()
        owner,foreign,subject=[uuid4() for _ in range(3)]
        for uid in (owner,foreign):conn.execute('insert into auth.users(id) values(%s)',(uid,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Automation rollback')",(subject,owner))
        def rejects(code,operation):
            try:
                with conn.transaction():operation()
            except psycopg.Error as exc:assert exc.sqlstate==code,str(exc)
            else:raise AssertionError(f'Expected {code}')
        def schedule(enabled=True,version=0,uid=owner):return conn.execute('select save_daily_review_schedule(%s,%s,%s,0,%s)',(uid,subject,enabled,version)).fetchone()[0]
        rejects('42501',lambda:schedule(uid=foreign));assert schedule()['version']==1
        rejects('40001',lambda:schedule())
        for _ in range(3):conn.execute('select enqueue_daily_review_jobs()')
        jobs=conn.execute('select id from learning_job_outbox where user_id=%s',(owner,)).fetchall();assert len(jobs)==1
        job=jobs[0][0]
        def claim():return conn.execute('select claim_learning_job(%s)',(job,)).fetchone()[0]
        def finish(token,error=None):return conn.execute('select finish_learning_job(%s,%s,%s)',(job,token,error)).fetchone()[0]
        first=claim();assert first['attempts']==1 and claim() is None
        conn.execute("update learning_job_outbox set lease_until=now()-interval '1 second' where id=%s",(job,))
        second=claim();assert second['claim_token']!=first['claim_token'] and not finish(first['claim_token'])
        source=conn.execute('select daily_learning_source(%s,%s,%s)',(owner,subject,second['day'])).fetchone()[0]
        report=build_learning_review_graph().invoke({'source':source})['report']
        def publish(token):return conn.execute('select publish_daily_review_job(%s,%s,%s,%s)',(job,token,Jsonb(source),Jsonb(report))).fetchone()[0]
        rejects('40001',lambda:publish(first['claim_token']))
        result=publish(second['claim_token']);assert result['status']=='pending'
        for _ in range(3):assert claim() is None
        assert conn.execute('select count(*) from daily_learning_reviews where user_id=%s',(owner,)).fetchone()[0]==1
        assert conn.execute('select status from learning_job_outbox where id=%s',(job,)).fetchone()[0]=='succeeded'
        # Simulate another job for failure/disable fencing without changing real users.
        conn.execute('delete from daily_learning_reviews where user_id=%s',(owner,))
        conn.execute("update learning_job_outbox set status='queued',attempts=0,available_at=now(),result_id=null where id=%s",(job,))
        live=claim();schedule(False,1)
        rejects('40001',lambda:publish(live['claim_token']))
        assert not finish(live['claim_token'])
        schedule(True,2)
        conn.execute("update learning_job_outbox set status='queued',attempts=0,available_at=now() where id=%s",(job,))
        for count in range(1,6):
            token=claim()['claim_token'];assert finish(token,'fixture_error')
            state=conn.execute('select status,attempts from learning_job_outbox where id=%s',(job,)).fetchone()
            assert state==('dead' if count==5 else 'queued',count)
            conn.execute('update learning_job_outbox set available_at=now() where id=%s',(job,))
        assert claim() is None
        conn.execute("update learning_job_outbox set status='queued',day=day-1,attempts=0 where id=%s",(job,));assert claim() is None
        assert conn.execute('select error_code from learning_job_outbox where id=%s',(job,)).fetchone()[0]=='day_expired'
        conn.execute('set local role authenticated');conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        rejects('42501',lambda:schedule());rejects('42501',claim)
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from learning_job_outbox').fetchone()[0]==0
        conn.execute('reset role');conn.execute('delete from subjects where id=%s',(subject,))
        assert conn.execute('select count(*) from learning_job_outbox where user_id=%s',(owner,)).fetchone()[0]==0
        conn.rollback();print('PASS: opt-in/CAS, daily enqueue dedup x3, exclusive claim/lease recovery/token fence, atomic report+ack/no auto-plan decision, disable fencing, bounded retry/dead/expiry, RLS/private RPC/cascade; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY']='localhost,127.0.0.1,::1';os.environ['no_proxy']=os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row=conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row:raise SystemExit('No local subject')
            app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    for path in ('/api/v1/daily-reviews','/api/v1/daily-reviews/schedule'):
                        response=client.get(path,params={'subject_id':str(row[0])});assert response.status_code==200,response.text
                        assert client.get(path,params={'subject_id':str(uuid4())}).status_code==404
                    cursor=client.get('/api/v1/daily-reviews',params={'subject_id':str(row[0]),'before':'2100-01-01T00:00:00Z','before_id':str(uuid4())})
                    assert cursor.status_code==200,cursor.text
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/daily-reviews/schedule',params={'subject_id':str(row[0])}).status_code==401
            print('PASS: actual Supabase history/schedule read API 200/404/401; auth override, no real user writes')


if __name__=='__main__':main()
