"""Local-only daily learning review SQL/API verification. No models; fixtures roll back."""
import argparse
import os
import re
import sys
from datetime import timedelta
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
        migration=(Path(__file__).resolve().parents[1]/'migrations/051_daily_learning_reviews.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.daily_learning_reviews')").fetchone()[0]:
            if not args.apply:raise SystemExit('Missing 051; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 051')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;',migration,re.S):conn.execute(sql.replace('create function','create or replace function',1))
            conn.execute("notify pgrst,'reload schema'");conn.commit()
        owner,foreign,subject,other,topic,plan,other_plan,task,task2,request=[uuid4() for _ in range(10)]
        for uid in (owner,foreign):conn.execute('insert into auth.users(id) values(%s)',(uid,))
        for sid in (subject,other):conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Daily rollback')",(sid,owner))
        day=conn.execute("select (now() at time zone 'Asia/Shanghai')::date").fetchone()[0]
        for pid,sid in ((plan,subject),(other_plan,other)):
            conn.execute("insert into study_plans(id,user_id,subject_id,title,exam_date,daily_minutes) values(%s,%s,%s,'Plan',%s+30,60)",(pid,owner,sid,day))
        conn.execute("insert into knowledge_points(id,user_id,subject_id,title,knowledge_key) values(%s,%s,%s,'Position Encoding','stable-key')",(topic,owner,subject))
        conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery,confidence,attempts) values(%s,%s,'stable-key',.4,.7,3)",(owner,subject))
        for score,stamp in ((.28,'-1 hour'),(.4,'+1 hour')):
            conn.execute("insert into mastery_history(user_id,subject_id,knowledge_key,mastery,confidence,correct,difficulty,created_at) values(%s,%s,'stable-key',%s,.7,true,'medium',(%s::date::timestamp at time zone 'Asia/Shanghai')+%s::interval)",(owner,subject,score,day,stamp))
        def new_task(tid,pid,sid,scheduled,minutes=20,locked=False,source='system'):
            conn.execute("insert into review_tasks(id,user_id,subject_id,plan_id,knowledge_key,knowledge_point_id,task_type,title,scheduled_date,estimated_minutes,priority,locked,source) values(%s,%s,%s,%s,'stable-key',%s,'practice','Task',%s,%s,.8,%s,%s)",
                (tid,owner,sid,pid,topic if sid==subject else None,scheduled,minutes,locked,source))
        new_task(task,plan,subject,day);new_task(task2,plan,subject,day-timedelta(days=1))
        new_task(uuid4(),plan,subject,day-timedelta(days=2),locked=True)
        new_task(uuid4(),plan,subject,day-timedelta(days=3),source='user')
        new_task(uuid4(),other_plan,other,day+timedelta(days=1),minutes=80)
        conn.execute('insert into calendar_availability(user_id,day,minutes) values(%s,%s+1,110)',(owner,day))
        def read(uid=owner):return conn.execute('select daily_learning_source(%s,%s,%s)',(uid,subject,day)).fetchone()[0]
        def rejects(code,operation):
            try:
                with conn.transaction():operation()
            except psycopg.Error as exc:assert exc.sqlstate==code,str(exc)
            else:raise AssertionError(f'Expected {code}')
        def report(src):return build_learning_review_graph().invoke({'source':src})['report']
        def save(src,output,req=request):return conn.execute('select save_daily_learning_review(%s,%s,%s,%s,%s,%s)',(owner,subject,day,req,Jsonb(src),Jsonb(output))).fetchone()[0]
        def decide(rid,approve=True,version=1,uid=owner):return conn.execute('select decide_daily_learning_review(%s,%s,%s,%s)',(uid,rid,version,approve)).fetchone()[0]
        rejects('42501',lambda:read(foreign))
        src=read();output=report(src)
        assert len(src['candidates'])==2 and len(output['proposedMoves'])==1
        assert output['masteryChanges'][0]['deltaPoints']==12 and output['feasibility']['existingMinutes']==80
        assert len(output['unresolvedProblems'])==1
        saved=save(src,output);rid=saved['id']
        assert save(src,output)['id']==rid and saved['status']=='pending'
        rejects('42501',lambda:decide(rid,uid=foreign));rejects('40001',lambda:decide(rid,version=99))
        conn.execute('update calendar_availability set minutes=111 where user_id=%s',(owner,))
        rejects('40001',lambda:decide(rid))
        conn.execute('update calendar_availability set minutes=110 where user_id=%s',(owner,))
        # Deliberately oversized trusted draft verifies rollback after first task moves.
        bad={**output,'proposedMoves':[{'taskId':c['id'],'planId':c['planId'],'topicId':c['topicId'],'minutes':c['minutes']} for c in src['candidates']]}
        bad_review=save(src,bad,uuid4())
        rejects('40001',lambda:decide(bad_review['id']))
        assert conn.execute('select count(*) from review_tasks where id in (%s,%s) and scheduled_date<=%s',(task,task2,day)).fetchone()[0]==2
        applied=decide(rid);assert applied['status']=='applied' and applied['version']==2
        assert decide(rid)['status']=='applied'
        rejects('40001',lambda:decide(rid,approve=False))
        moved=output['proposedMoves'][0]['taskId']
        assert conn.execute('select locked from review_tasks where id=%s',(moved,)).fetchone()[0]
        assert conn.execute('select count(*) from study_plan_events where user_id=%s and event_type=%s',(owner,'calendar_moved')).fetchone()[0]==1
        assert conn.execute('select count(*) from study_plan_events where user_id=%s and event_type=%s',(owner,'daily_review_applied')).fetchone()[0]==1
        current=read();rejected=save(current,report(current),uuid4());assert decide(rejected['id'],approve=False)['status']=='rejected'
        assert conn.execute('select mastery from knowledge_mastery where user_id=%s',(owner,)).fetchone()[0]==.4
        conn.execute('set local role authenticated');conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        rejects('42501',lambda:read());rejects('42501',lambda:decide(rid))
        rejects('42501',lambda:conn.execute('delete from daily_learning_reviews where id=%s',(rid,)))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from daily_learning_reviews').fetchone()[0]==0
        conn.execute('reset role');conn.execute('delete from subjects where id=%s',(subject,))
        assert conn.execute('select count(*) from daily_learning_reviews where user_id=%s',(owner,)).fetchone()[0]==0
        conn.rollback();print('PASS: canonical history delta +12 points, weak Topic, shared capacity/protected tasks, request replay, stale/foreign/version guards, partial batch rollback, confirmed calendar write/event/lock, decision replay/reject, no mastery write, RLS/private RPC/cascade; fixtures rolled back')
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
                    response=client.get('/api/v1/daily-reviews/preview',params={'subject_id':str(row[0])})
                    assert response.status_code==200,response.text
                    assert client.get('/api/v1/daily-reviews/preview',params={'subject_id':str(uuid4())}).status_code==404
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/daily-reviews/preview',params={'subject_id':str(row[0])}).status_code==401
            print('PASS: actual Supabase read-only preview API 200/404/401; test auth override, no real user plan writes or model calls')


if __name__=='__main__':main()
