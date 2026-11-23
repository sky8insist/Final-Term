"""Local-only Mind Map binding acceptance. Fixture writes always roll back."""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--api', action='store_true')
    args = parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Local database required')
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        sql = (Path(__file__).resolve().parents[1] / 'migrations/049_mind_map_topics.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.mind_map_topic_links')").fetchone()[0]:
            if not args.apply: raise SystemExit('Missing 049; use --apply locally')
            conn.execute(sql); conn.commit(); print('Applied local 049')
        elif args.apply:
            for fn in re.findall(r'create function .*?\$\$;', sql, re.S):
                conn.execute(fn.replace('create function', 'create or replace function', 1))
            conn.execute("notify pgrst,'reload schema'"); conn.commit()
        owner, foreign, subject, other_subject, art, topic, other_topic, cards, exam = [uuid4() for _ in range(9)]
        for uid in (owner, foreign): conn.execute('insert into auth.users(id) values(%s)', (uid,))
        for sid in (subject, other_subject):
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Map rollback')", (sid,owner))
        for tid,sid in ((topic,subject),(other_topic,other_subject)):
            conn.execute("insert into knowledge_points(id,user_id,subject_id,title,knowledge_key) values(%s,%s,%s,'Same display title',%s)", (tid,owner,sid,str(tid)))
        nodes = [{'id':'root','label':'Root','mastery':.99},{'id':'n','label':'Same display title','parentId':'root','mastery':.99}]
        conn.execute("insert into artifacts(id,user_id,subject_id,artifact_type,title,content) values(%s,%s,%s,'mind_map','Map',%s)", (art,owner,subject,Jsonb({'nodes':nodes})))
        def read(uid=owner): return conn.execute('select read_mind_map_learning(%s,%s)', (uid,art)).fetchone()[0]
        def bind(av,bv,tid=topic,uid=owner,node='n'):
            return conn.execute('select bind_mind_map_topic(%s,%s,%s,%s,%s,%s)', (uid,art,node,tid,av,bv)).fetchone()[0]
        def rejects(code, operation):
            try:
                with conn.transaction(): operation()
            except psycopg.Error as exc: assert exc.sqlstate == code, str(exc)
            else: raise AssertionError(f'Expected {code}')
        assert read()['nodes']['n']['knowledgePointId'] is None
        rejects('42501', lambda: read(foreign))
        rejects('42501', lambda: bind(1,0,uid=foreign))
        rejects('22023', lambda: bind(1,0,tid=other_topic))
        rejects('22023', lambda: bind(1,0,node='missing'))
        assert bind(1,0) == {'artifactVersion':2,'bindingVersion':1}
        rejects('40001', lambda: bind(1,1))
        rejects('40001', lambda: bind(2,0))
        bound = read()['nodes']['n']
        assert bound['knowledgePointId'] == str(topic) and bound['mastery'] is None and not bound['covered']
        assert conn.execute('select count(*) from topic_coverage where user_id=%s',(owner,)).fetchone()[0] == 0
        conn.execute('insert into topic_coverage(user_id,subject_id,knowledge_point_id) values(%s,%s,%s)', (owner,subject,topic))
        conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery,confidence,attempts,metadata) values(%s,%s,%s,.93,.8,3,%s)",
                     (owner,subject,str(topic),Jsonb({'assessmentCount':3,'assessmentCorrectStreak':3})))
        assert read()['nodes']['n']['mastery']['mastery'] == .93 and read()['nodes']['n']['covered']
        card_content = {'cards':[{'id':'card','front':'Question','back':'Answer','knowledgePointId':str(topic)}]}
        conn.execute("insert into artifacts(id,user_id,subject_id,artifact_type,title,content) values(%s,%s,%s,'flashcards','Cards',%s)",(cards,owner,subject,Jsonb(card_content)))
        conn.execute("update flashcard_review_state set next_review=now()-interval '1 day' where artifact_id=%s",(cards,))
        conn.execute("insert into exam_events(id,user_id,subject_id,title,exam_date) values(%s,%s,%s,'Upcoming',current_date+30)",(exam,owner,subject))
        conn.execute('insert into exam_topic_map(exam_event_id,user_id,subject_id,knowledge_point_id,weight) values(%s,%s,%s,%s,2)',(exam,owner,subject,topic))
        assert read()['nodes']['n']['dueCards'] == 1 and read()['nodes']['n']['exams'][0]['id'] == str(exam)
        conn.execute("update exam_events set status='archived' where id=%s",(exam,))
        assert read()['nodes']['n']['exams'] == []
        conn.execute('update knowledge_points set title=%s where id=%s',('Renamed stable topic',topic))
        assert read()['nodes']['n']['topicTitle'] == 'Renamed stable topic'
        conn.execute('update knowledge_points set archived=true where id=%s',(topic,))
        stale = read()['nodes']['n']
        assert stale['stale'] and stale['knowledgePointId'] is None and stale['mastery'] is None and stale['dueCards'] == 0
        rejects('22023',lambda:bind(2,1))
        conn.execute('update knowledge_points set archived=false where id=%s',(topic,))
        assert bind(2,0,node='root')['artifactVersion'] == 3
        nodes[1]['description'] = 'Edited source'
        conn.execute('update artifacts set content=%s,version=version+1 where id=%s',(Jsonb({'nodes':nodes}),art))
        state = read()
        assert state['nodes']['n']['stale'] and not state['nodes']['root']['stale']
        assert bind(4,1)['artifactVersion'] == 5
        assert not read()['nodes']['n']['stale']
        assert bind(5,2,tid=None)['bindingVersion'] == 3
        assert read()['nodes']['n']['knowledgePointId'] is None and not read()['nodes']['n']['stale']
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        assert conn.execute('select count(*) from mind_map_topic_links').fetchone()[0] == 2
        rejects('42501',lambda:read())
        rejects('42501',lambda:bind(6,3))
        rejects('42501',lambda:conn.execute('delete from mind_map_topic_links where artifact_id=%s',(art,)))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from mind_map_topic_links').fetchone()[0] == 0
        conn.execute('reset role')
        conn.execute('delete from artifacts where id=%s',(art,))
        assert conn.execute('select count(*) from mind_map_topic_links where artifact_id=%s',(art,)).fetchone()[0] == 0
        conn.rollback()
        print('PASS: owner/scope/node guards, two-version CAS, no invented coverage/mastery, immutable-key state, rename/archive, due cards/exams, per-node snapshot invalidation/rebind/unlink, RLS/private RPC/cascade; all fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}: raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'; os.environ['no_proxy'] = os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row = conn.execute("select id,user_id from artifacts where artifact_type='mind_map' order by created_at limit 1").fetchone()
            if not row: raise SystemExit('No local saved map for API read')
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    response = client.get(f'/api/v1/artifacts/{row[0]}/learning')
                    assert response.status_code == 200, response.text
                    assert 'nodes' in response.json()
                    assert client.get(f'/api/v1/artifacts/{uuid4()}/learning').status_code == 404
            finally: app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client: assert client.get(f'/api/v1/artifacts/{row[0]}/learning').status_code == 401
            print('PASS: real local Supabase read API 200/missing 404/anonymous 401; auth override; no real user writes or model calls')


if __name__ == '__main__': main()
