"""Local event/outbox acceptance; all business fixtures roll back, no paid/broker calls."""
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


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--api',action='store_true');args=parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local DB required')
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        migration=(Path(__file__).resolve().parents[1]/'migrations/053_learning_domain_events.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.learning_domain_events')").fetchone()[0]:
            if not args.apply:raise SystemExit('Missing 053; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 053')
        elif args.apply:
            if not conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name='study_plans' and column_name='replan_dirty_since')").fetchone()[0]:
                conn.execute('alter table study_plans add column replan_dirty_since timestamptz')
            for sql in re.findall(r'create (?:or replace )?function .*?\$\$;',migration,re.S):conn.execute(sql.replace('create function','create or replace function',1))
            if not conn.execute("select exists(select 1 from pg_trigger where tgname='replan_dirty_window' and tgrelid='public.study_plans'::regclass)").fetchone()[0]:
                conn.execute('create trigger replan_dirty_window before insert or update of replan_required on study_plans for each row execute function track_replan_dirty_since()')
            conn.execute("notify pgrst,'reload schema'");conn.commit()
        owner,foreign,subject,plan,topic,material,exam,blueprint,cards,task=[uuid4() for _ in range(10)]
        for uid in (owner,foreign):conn.execute('insert into auth.users(id) values(%s)',(uid,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Events rollback')",(subject,owner))
        conn.execute("insert into study_plans(id,user_id,subject_id,title,exam_date,daily_minutes,strategy) values(%s,%s,%s,'Plan',current_date+30,60,%s)",(plan,owner,subject,Jsonb({'algorithmVersion':'exam-state-scheduler-v3','autoReplan':True})))
        conn.execute("insert into knowledge_points(id,user_id,subject_id,title,knowledge_key) values(%s,%s,%s,'Topic','stable')",(topic,owner,subject))
        conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery) values(%s,%s,'stable',.4)",(owner,subject))
        conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'fixture.txt','text/plain',5,'ready')",(material,owner,subject))
        conn.execute("insert into exam_blueprints(id,user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,%s,'Exam',30,10,'{}')",(blueprint,owner,subject))
        conn.execute("insert into exams(id,user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,%s,'Exam',30,10)",(exam,owner,subject,blueprint))
        conn.execute("insert into exam_attempts(user_id,subject_id,exam_id,status,expires_at,submitted_at) values(%s,%s,%s,'graded',now()+interval '1 hour',now())",(owner,subject,exam))
        conn.execute("insert into exam_events(user_id,subject_id,title,exam_date) values(%s,%s,'Target',current_date+10)",(owner,subject))
        conn.execute("insert into artifacts(id,user_id,subject_id,artifact_type,title,content) values(%s,%s,%s,'flashcards','Cards',%s)",(cards,owner,subject,Jsonb({'cards':[{'id':'c','front':'Q','back':'A'}]})))
        conn.execute("insert into flashcard_review_logs(id,user_id,subject_id,artifact_id,card_id,rating,expected_version,content_version,state_before,state_after,result) values(%s,%s,%s,%s,'c','good',0,1,'{}','{}','{}')",(uuid4(),owner,subject,cards))
        conn.execute("insert into review_tasks(id,user_id,subject_id,plan_id,knowledge_key,knowledge_point_id,task_type,title,scheduled_date,estimated_minutes,priority) values(%s,%s,%s,%s,'stable',%s,'practice','Missed',(now() at time zone 'Asia/Shanghai')::date-1,20,.8)",(task,owner,subject,plan,topic))
        for _ in range(3):conn.execute('select enqueue_learning_due_events()')
        kinds={r[0] for r in conn.execute('select event_type from learning_domain_events where user_id=%s',(owner,))}
        assert kinds=={'material.indexed','exam.completed','mastery.changed','flashcard.reviewed','exam.updated','task.missed'},kinds
        assert conn.execute("select count(*) from learning_domain_events where user_id=%s and event_type='task.missed'",(owner,)).fetchone()[0]==1
        events=conn.execute('select count(*) from learning_domain_events where user_id=%s',(owner,)).fetchone()[0]
        assert conn.execute("select count(*) from learning_job_outbox where user_id=%s and kind='projection_refresh'",(owner,)).fetchone()[0]==events
        # A failing source transaction must not leave an event or job.
        try:
            with conn.transaction():
                conn.execute("update knowledge_mastery set mastery=.8 where user_id=%s",(owner,));raise RuntimeError('rollback source')
        except RuntimeError:pass
        assert conn.execute('select count(*) from learning_domain_events where user_id=%s',(owner,)).fetchone()[0]==events
        assert not any(str(row[0])==str(plan) for row in conn.execute('select id from study_plan_replan_candidates()'))
        job,event=conn.execute("select j.id,e.id from learning_job_outbox j join learning_domain_events e on e.id=j.source_id where j.user_id=%s and e.event_type='mastery.changed'",(owner,)).fetchone()
        conn.execute('update learning_job_outbox set available_at=now() where id=%s',(job,))
        claimed=conn.execute('select claim_learning_job(%s)',(job,)).fetchone()[0]
        def consume():return conn.execute('select consume_learning_projection_job(%s,%s)',(job,claimed['claim_token'])).fetchone()[0]
        assert consume()['consumed']
        version=conn.execute('select version from learning_projection_versions where user_id=%s',(owner,)).fetchone()[0]
        for _ in range(3):assert not consume()['consumed']
        assert conn.execute('select version from learning_projection_versions where user_id=%s',(owner,)).fetchone()[0]==version==1
        assert conn.execute('select consumed_at is not null from learning_domain_events where id=%s',(event,)).fetchone()[0]
        conn.execute("update study_plans set replan_dirty_since=now()-interval '3 minutes' where id=%s",(plan,))
        assert any(str(row[0])==str(plan) for row in conn.execute('select id from study_plan_replan_candidates()'))
        def rejects(code,operation):
            try:
                with conn.transaction():operation()
            except psycopg.Error as exc:assert exc.sqlstate==code,str(exc)
            else:raise AssertionError(f'Expected {code}')
        dead=conn.execute("select id from learning_job_outbox where user_id=%s and status='queued' limit 1",(owner,)).fetchone()[0]
        conn.execute("update learning_job_outbox set status='dead',attempts=5 where id=%s",(dead,))
        def retry(uid=owner):return conn.execute('select retry_learning_job(%s,%s)',(uid,dead)).fetchone()[0]
        rejects('42501',lambda:retry(foreign))
        for n in range(1,4):
            assert retry()['manual_retries']==n
            rejects('40001',retry)
            conn.execute("update learning_job_outbox set status='dead',attempts=5 where id=%s",(dead,))
        rejects('40001',retry)
        conn.execute('set local role authenticated');conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        rejects('42501',consume);rejects('42501',retry)
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from learning_domain_events').fetchone()[0]==0
        conn.execute('reset role');conn.execute('delete from subjects where id=%s',(subject,))
        for table in ('learning_job_outbox','learning_domain_events','learning_projection_versions'):
            assert conn.execute(f'select count(*) from {table} where user_id=%s',(owner,)).fetchone()[0]==0
        conn.rollback();print('PASS: six transactional event producers/outbox, source rollback, missed-task dedup x3, atomic consume/receipt/epoch x3 unchanged, debounce/max-wait, bounded manual dead retry/scope, private RPC/RLS/cascade; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY']='localhost,127.0.0.1,::1';os.environ['no_proxy']=os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row=conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    response=client.get('/api/v1/learning-jobs',params={'subject_id':str(row[0])});assert response.status_code==200,response.text
                    assert client.get('/api/v1/learning-jobs',params={'subject_id':str(uuid4())}).status_code==404
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/learning-jobs',params={'subject_id':str(row[0])}).status_code==401
            print('PASS: actual Supabase job status read API 200/404/401; test authentication, no real user effects')


if __name__=='__main__':main()
