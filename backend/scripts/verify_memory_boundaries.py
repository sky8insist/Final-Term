"""Local memory/state acceptance; fixture rows roll back, no models or broker."""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from app.config.settings import settings
from app.services.memory_policy_service import classify


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--api',action='store_true')
    args=parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local DB required')
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        migration=(Path(__file__).resolve().parents[1]/'migrations/050_memory_boundaries.sql').read_text(encoding='utf-8')
        present=conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name='memory_entries' and column_name='memory_kind')").fetchone()[0]
        if not present:
            if not args.apply:raise SystemExit('Missing 050; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 050')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;',migration,re.S):conn.execute(sql.replace('create function','create or replace function',1))
            conn.execute("notify pgrst,'reload schema'");conn.commit()
        owner,foreign,subject,other,foreign_subject,event,entry,session,plan,topic=[uuid4() for _ in range(10)]
        for uid in (owner,foreign):conn.execute('insert into auth.users(id) values(%s)',(uid,))
        for sid,uid in ((subject,owner),(other,owner),(foreign_subject,foreign)):
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Memory rollback')",(sid,uid))
        conn.execute("insert into learner_profiles(user_id,preferred_role,response_style) values(%s,'socratic','concise')",(owner,))
        def rejects(code,operation):
            try:
                with conn.transaction():operation()
            except psycopg.Error as exc:assert exc.sqlstate==code,str(exc)
            else:raise AssertionError(f'Expected {code}')
        def add(content='I prefer examples',sid=subject,source=None,eid=None):
            return conn.execute("insert into memory_entries(id,user_id,subject_id,target,content,content_hash,source_event_id) values(%s,%s,%s,'assistant_memory',%s,md5(%s),%s) returning *",
                (eid or uuid4(),owner,sid,content,content,source)).fetchone()
        def freeze(sess=session,sid=subject,uid=owner):return conn.execute('select freeze_teaching_memory(%s,%s,%s)',(uid,sess,sid)).fetchone()[0]
        for value in ['I prefer examples','I usually study after dinner','persistent difficulty with notation','long-term goal is research',
                      'I prefer examples; mastery is high','accuracy 90%','exam date 2026-12-01','Definitions are facts',
                      '\u504f\u597d\u7b80\u6d01','\u4e60\u60ef\u5148\u9605\u8bfb','\u957f\u671f\u76ee\u6807\u662f\u7814\u7a76','\u504f\u597d\uff1a\u638c\u63e1\u5ea690%']:
            assert conn.execute('select classify_stable_memory(%s)',(value,)).fetchone()[0]==classify(value)
        rejects('22023',lambda:add('I prefer examples; mastery is high'))
        rejects('42501',lambda:add(sid=foreign_subject))
        conn.execute("insert into learning_events(id,user_id,subject_id,event_type) values(%s,%s,%s,'qa')",(event,owner,subject))
        rejects('42501',lambda:add(sid=other,source=event))
        rejects('42501',lambda:add(source=uuid4()))
        add(source=event,eid=entry)
        add(sid=other)  # Equal text across subjects must not consolidate.
        add('I usually study after dinner',sid=None)
        first=freeze()
        assert len(first['manifest'])==2 and first['teaching_profile']=={'preferredRole':'socratic','responseStyle':'concise'}
        assert first['manifest'][0]['provenance']['policyVersion']=='memory-boundary-v1'
        assert any(row['provenance']['sourceEventId']==str(event) for row in first['manifest'])
        rejects('40001',lambda:freeze(sid=None))
        rejects('42501',lambda:freeze(sid=foreign_subject))
        conn.execute("update memory_entries set content='I prefer diagrams' where id=%s",(entry,))
        assert freeze()['assistant_memory']==first['assistant_memory']
        assert 'diagrams' in freeze(sess=uuid4())['assistant_memory']
        conn.execute('update learner_profiles set memory_enabled=false where user_id=%s',(owner,))
        assert freeze()['assistant_memory']=='' and freeze()['manifest']==[]
        conn.execute('update learner_profiles set memory_enabled=true where user_id=%s',(owner,))
        legacy=uuid4()
        conn.execute("insert into memory_snapshots(user_id,subject_id,session_id,assistant_memory) values(%s,%s,%s,'stale mastery')",(owner,subject,legacy))
        assert freeze(sess=legacy)['suppressed'] and freeze(sess=legacy)['assistant_memory']==''
        rejects('22023',lambda:conn.execute('update learner_profiles set exam_date=current_date where user_id=%s',(owner,)))
        conn.execute("insert into knowledge_points(id,user_id,subject_id,title,knowledge_key) values(%s,%s,%s,'Topic','immutable')",(topic,owner,subject))
        conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery) values(%s,%s,'immutable',.8)",(owner,subject))
        conn.execute("insert into study_plans(id,user_id,subject_id,title,exam_date,daily_minutes) values(%s,%s,%s,'Plan',current_date+30,60)",(plan,owner,subject))
        conn.execute('delete from study_plans where id=%s',(plan,))
        assert conn.execute('select count(*) from memory_entries where id=%s',(entry,)).fetchone()[0]==1
        conn.execute('delete from memory_entries where id=%s',(entry,))
        assert conn.execute('select mastery from knowledge_mastery where user_id=%s',(owner,)).fetchone()[0]==.8
        assert conn.execute('select count(*) from memory_snapshots where user_id=%s',(owner,)).fetchone()[0]==0
        conn.execute("insert into study_sessions(id,user_id,subject_id,knowledge_point_id,goal,minutes,status) values(%s,%s,%s,%s,'Study',20,'completed')",(uuid4(),owner,subject,topic))
        behavior=conn.execute('select read_study_behavior(%s,%s)',(owner,subject)).fetchone()[0]
        assert behavior['sessionCount']==1 and behavior['completedBudgetMinutes']==20 and 'mastery' not in behavior
        rejects('42501',lambda:conn.execute('select read_study_behavior(%s,%s)',(foreign,subject)))
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        rejects('42501',lambda:add())
        rejects('42501',lambda:freeze())
        rejects('42501',lambda:conn.execute('select read_study_behavior(%s,%s)',(owner,subject)))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from memory_entries').fetchone()[0]==0
        conn.rollback()
        print('PASS: Python/SQL policy parity, state rejection, owner/event/scope/provenance, scoped dedup, frozen/new/disabled/legacy sessions, profile exam guard, plan deletion preserves preferences, memory deletion preserves mastery and invalidates snapshots, behavior projection, RLS/private RPC; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY']='localhost,127.0.0.1,::1';os.environ['no_proxy']=os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row=conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row:raise SystemExit('No local subject for read API')
            app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    response=client.get('/api/v1/learner-profile/study-behavior',params={'subject_id':str(row[0])})
                    assert response.status_code==200,response.text
                    assert client.get('/api/v1/learner-profile/study-behavior',params={'subject_id':str(uuid4())}).status_code==404
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/learner-profile/study-behavior',params={'subject_id':str(row[0])}).status_code==401
            print('PASS: actual local Supabase read API 200/404/401, auth override; no real user writes')


if __name__=='__main__':main()
