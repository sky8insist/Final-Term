"""Calendar local SQL and read-only API acceptance; fixture writes roll back."""
import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--api',action='store_true')
    args=parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local database required')
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        migration=(Path(__file__).resolve().parents[1]/'migrations/044_learning_calendar.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.calendar_availability')").fetchone()[0]:
            if not args.apply:raise SystemExit('Missing 044; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 044')
        elif args.apply:
            # Refresh only this module's function bodies, not the historical rename.
            import re
            functions=re.findall(r'create function .*?\$\$;',migration,re.S)
            for sql in functions:conn.execute(sql.replace('create function','create or replace function',1))
            conn.execute('create index if not exists review_tasks_calendar_idx on public.review_tasks(user_id,scheduled_date,plan_id)')
            conn.execute("notify pgrst,'reload schema'");conn.commit();print('Refreshed local calendar functions')
        conn.execute("select set_config('request.jwt.claims','{\"role\":\"service_role\"}',true)")
        owner,foreign,subject,other_subject=[uuid4() for _ in range(4)]
        for uid in [owner,foreign]:conn.execute('insert into auth.users(id) values(%s)',(uid,))
        for sid in [subject,other_subject]:conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Calendar rollback')",(sid,owner))
        day=conn.execute("select (now() at time zone 'Asia/Shanghai')::date").fetchone()[0]
        def rejects(code,operation):
            try:
                with conn.transaction():operation()
            except psycopg.Error as exc:assert exc.sqlstate==code,(exc.sqlstate,str(exc))
            else:raise AssertionError('Invalid calendar action accepted')
        def available(target,minutes,version=0):return conn.execute('select save_calendar_availability(%s,%s,%s,%s)',(owner,target,minutes,version)).fetchone()[0]
        assert available(day,60)['version']==1
        rejects('40001',lambda:available(day,30))
        rejects('23514',lambda:available(day,-1,1))
        rejects('22023',lambda:available(day-timedelta(days=1),60))
        topic=conn.execute("select (resolve_course_topic(%s,%s,'Calendar Topic')).id",(owner,subject)).fetchone()[0]
        other_topic=conn.execute("select (resolve_course_topic(%s,%s,'Other Topic')).id",(owner,other_subject)).fetchone()[0]
        values={'title':'Calendar plan','exam_date':(day+timedelta(days=10)).isoformat(),'daily_minutes':60,'mode':'STANDARD','strategy':{'algorithmVersion':'exam-state-scheduler-v3','autoReplan':True}}
        def task(tid=topic,amount=40,target=day):return {'knowledge_key':'Calendar Topic','knowledge_point_id':str(tid),'task_type':'concept_rebuild','title':'Study','scheduled_date':target.isoformat(),'estimated_minutes':amount,'priority':1,'metadata':{}}
        def save(sid,items,pid=None,version=0):return conn.execute('select to_jsonb(save_study_plan_v3(%s,%s,%s,%s,%s,%s,true))',(owner,sid,pid,version,Jsonb(values),Jsonb(items))).fetchone()[0]
        plan=save(subject,[task()])
        rejects('40001',lambda:save(other_subject,[task(other_topic,30)]))
        assert conn.execute('select count(*) from study_plans where user_id=%s',(owner,)).fetchone()[0]==1
        save(other_subject,[task(other_topic,20)])
        capacity=conn.execute('select calendar_plan_capacity(%s,%s,%s,%s)',(owner,day,day,plan['id'])).fetchone()[0]
        assert capacity[day.isoformat()]==40
        available(day,30,1)
        feed=conn.execute('select learning_calendar(%s,%s,%s,null)',(owner,day,day)).fetchone()[0]
        assert feed[0]['minutes']==30 and feed[0]['plannedMinutes']==60 and len(feed[0]['tasks'])==2
        scoped=conn.execute('select learning_calendar(%s,%s,%s,%s)',(owner,day,day,subject)).fetchone()[0]
        assert scoped[0]['plannedMinutes']==60 and len(scoped[0]['tasks'])==1
        card_content={'cards':[{'id':'c1','front':'Calendar definition?','back':'Definition','knowledgePointId':str(topic),'knowledgeKey':'Calendar Topic'}]}
        artifact=conn.execute("insert into artifacts(user_id,subject_id,artifact_type,title,content) values(%s,%s,'flashcards','Calendar cards',%s) returning id",(owner,subject,Jsonb(card_content))).fetchone()[0]
        conn.execute("update flashcard_review_state set next_review=now()-interval '3 days' where artifact_id=%s",(artifact,))
        def card_feed():return conn.execute('select learning_calendar(%s,%s,%s,null)',(owner,day,day)).fetchone()[0][0]
        assert card_feed()['dueCards']==1 and card_feed()['dueSubjects'][0]['count']==1
        conn.execute('update knowledge_points set archived=true where id=%s',(topic,))
        assert card_feed()['dueCards']==0
        conn.execute('update knowledge_points set archived=false where id=%s',(topic,))
        conn.execute('update flashcards set knowledge_point_id=null where artifact_id=%s',(artifact,))
        assert card_feed()['dueCards']==1  # Legacy cards without Topic match the existing queue.
        rejects('22023',lambda:conn.execute('select learning_calendar(%s,%s,%s,null)',(owner,day,day+timedelta(days=42))))
        target=day+timedelta(days=1)
        moving=conn.execute('select id from review_tasks where plan_id=%s',(plan['id'],)).fetchone()[0]
        version=lambda:conn.execute('select version from study_plans where id=%s',(plan['id'],)).fetchone()[0]
        def move(uid=owner,ver=None):return conn.execute('select move_calendar_task(%s,%s,%s,%s)',(uid,moving,target,ver if ver is not None else version())).fetchone()[0]
        rejects('42501',lambda:move(uid=foreign))
        rejects('22023',move)
        available(target,20)
        rejects('40001',move)
        available(target,60,1)
        old=version()
        rejects('40001',lambda:move(ver=old-1))
        assert move()['locked'] is True
        rejects('40001',move)
        assert conn.execute("select count(*) from study_plan_events where plan_id=%s and event_type='calendar_moved'",(plan['id'],)).fetchone()[0]==1
        # Completed and manual tasks cannot be moved, even if unlocked.
        for status,source in [('completed','system'),('pending','user')]:
            conn.execute('update review_tasks set locked=false,status=%s,source=%s where id=%s',(status,source,moving))
            rejects('40001',move)
        material=conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,'syllabus.txt','text/plain',1,'ready') returning id",(owner,subject)).fetchone()[0]
        block=conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,sequence_index,parser_name,parser_version,source_hash) values(%s,%s,%s,'paragraph','Final Exam: 2026-12-20',0,'test','1',%s) returning id",(owner,subject,material,str(uuid4()))).fetchone()[0]
        evidence=conn.execute('select note_source_citations(%s,%s,%s)',(owner,subject,[block])).fetchone()[0]
        def proposal():return conn.execute("insert into calendar_exam_proposals(user_id,subject_id,material_id,fingerprint,title,exam_date,evidence) values(%s,%s,%s,%s,'Final Exam',%s,%s) returning id",(owner,subject,material,str(uuid4()),day+timedelta(days=30),Jsonb(evidence))).fetchone()[0]
        candidate=proposal()
        exam_values={'title':'Confirmed final','exam_date':(day+timedelta(days=30)).isoformat(),'topics':[{'knowledge_point_id':str(topic),'weight':1}]}
        def confirm(pid=candidate,uid=owner,data=None):return conn.execute('select confirm_calendar_exam(%s,%s,%s)',(uid,pid,Jsonb(data or exam_values))).fetchone()[0]
        rejects('42501',lambda:confirm(uid=foreign))
        rejects('22023',lambda:confirm(data={**exam_values,'topics':[{'knowledge_point_id':str(other_topic),'weight':1}]}))
        event=confirm();assert confirm()['id']==event['id']
        assert conn.execute('select count(*) from exam_events where user_id=%s',(owner,)).fetchone()[0]==1
        assert conn.execute('select count(*) from exam_topic_map where exam_event_id=%s',(event['id'],)).fetchone()[0]==1
        conn.execute('select save_course_exam(%s,%s,null,%s)',(owner,other_subject,Jsonb({**exam_values,'topics':[{'knowledge_point_id':str(other_topic),'weight':1}]})))
        exam_day=day+timedelta(days=30)
        conflict=conn.execute('select learning_calendar(%s,%s,%s,%s)',(owner,exam_day,exam_day,subject)).fetchone()[0][0]
        assert conflict['globalExamCount']==2 and len(conflict['exams'])==1
        stale=proposal()
        conn.execute("update content_blocks set content_text='Changed' where id=%s",(block,))
        rejects('40001',lambda:confirm(pid=stale))
        # Read-only owner/RLS and RPC permissions.
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        assert conn.execute('select count(*) from calendar_availability').fetchone()[0]==2
        rejects('42501',lambda:conn.execute('select save_calendar_availability(%s,%s,1,1)',(owner,day)))
        rejects('42501',lambda:conn.execute('update calendar_availability set minutes=1 where user_id=%s',(owner,)))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from calendar_availability').fetchone()[0]==0
        assert conn.execute('select count(*) from calendar_exam_proposals').fetchone()[0]==0
        conn.rollback()
        print('PASS: availability CAS, shared subject capacity, atomic plan rollback, calendar aggregation, protected/missed task moves, exam confirmation replay/scope/evidence, private RPC and RLS; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY']='localhost,127.0.0.1,::1'
            os.environ['no_proxy']=os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row=conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row:raise SystemExit('No local subject for read-only API check')
            app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    params={'start':day.isoformat(),'end':(day+timedelta(days=6)).isoformat(),'subject_id':str(row[0])}
                    result=client.get('/api/v1/calendar',params=params)
                    assert result.status_code==200,(result.status_code,result.text[:300])
                    assert len(result.json()['days'])==7
                    params['subject_id']=str(uuid4())
                    assert client.get('/api/v1/calendar',params=params).status_code==404
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/calendar',params={'start':day.isoformat(),'end':day.isoformat()}).status_code==401
            print('PASS: real Supabase read-only calendar API, foreign subject 404, anonymous 401; auth override, no model calls')


if __name__=='__main__':main()
