"""Local lecture SQL/API acceptance. All fixture rows roll back; no ASR calls."""
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


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--api',action='store_true');args=parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local database required')
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        migration=(Path(__file__).resolve().parents[1]/'migrations/045_lecture_workspace.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.lectures')").fetchone()[0]:
            if not args.apply:raise SystemExit('Missing 045; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 045')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;',migration,re.S):conn.execute(sql.replace('create function','create or replace function',1))
            conn.execute("notify pgrst,'reload schema'");conn.commit();print('Refreshed local lecture functions')
        conn.execute("select set_config('request.jwt.claims','{\"role\":\"service_role\"}',true)")
        owner,foreign,subject,foreign_subject=[uuid4() for _ in range(4)]
        for uid in [owner,foreign]:conn.execute('insert into auth.users(id) values(%s)',(uid,))
        for sid,uid in [(subject,owner),(foreign_subject,foreign)]:conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Lecture rollback')",(sid,uid))
        def material(uid,sid,mime):return conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,'lecture.wav',%s,1,'ready') returning id",(uid,sid,mime)).fetchone()[0]
        audio=material(owner,subject,'audio/wav');other=material(foreign,foreign_subject,'audio/wav');text=material(owner,subject,'text/plain')
        def rejects(code,operation):
            try:
                with conn.transaction():operation()
            except psycopg.Error as exc:assert exc.sqlstate==code,(exc.sqlstate,str(exc))
            else:raise AssertionError('Invalid lecture operation accepted')
        def attach(mat=audio):return conn.execute("select attach_lecture(%s,%s,%s,'Lecture','upload')",(owner,subject,mat)).fetchone()[0]
        lecture=attach();assert attach()['id']==lecture['id'] and lecture['version']==1
        rejects('42501',lambda:attach(other));rejects('42501',lambda:attach(text))
        topic=conn.execute("select (resolve_course_topic(%s,%s,'Eigenvalues')).id",(owner,subject)).fetchone()[0]
        foreign_topic=conn.execute("select (resolve_course_topic(%s,%s,'Foreign')).id",(foreign,foreign_subject)).fetchone()[0]
        def block(uid=owner,sid=subject,mat=audio,index=0):return conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,start_time,end_time,sequence_index,parser_name,parser_version,source_hash) values(%s,%s,%s,'audio','Eigenvalue definition',%s,%s,%s,'test','1',%s) returning id",(uid,sid,mat,index*10,index*10+5,index,str(uuid4()))).fetchone()[0]
        first=block();other_block=block(foreign,foreign_subject,other)
        def align(version,tid=topic,bid=first,uid=owner):return conn.execute('select align_lecture_topic(%s,%s,%s,%s,%s)',(uid,lecture['id'],bid,tid,version)).fetchone()[0]
        before=conn.execute('select to_jsonb(k) from knowledge_mastery k where user_id=%s',(owner,)).fetchall()
        assert align(1)['version']==2
        rejects('40001',lambda:align(1))
        rejects('22023',lambda:align(2,foreign_topic))
        rejects('42501',lambda:align(2,bid=other_block))
        rejects('42501',lambda:align(2,uid=foreign))
        conn.execute('update knowledge_points set archived=true where id=%s',(topic,))
        rejects('22023',lambda:align(2))
        conn.execute('update knowledge_points set archived=false where id=%s',(topic,))
        def transcript(uid=owner,offset=0,bid=None):return conn.execute('select lecture_transcript(%s,%s,%s,50,%s)',(uid,lecture['id'],offset,bid)).fetchone()[0]
        assert transcript()['blocks'][0]['knowledge_point_id']==str(topic)
        assert align(2,tid=None)['version']==3 and transcript()['blocks'][0]['knowledge_point_id'] is None
        align(3)
        conn.execute("update content_blocks set content_text='Changed definition' where id=%s",(first,))
        assert transcript()['blocks'][0]['knowledge_point_id'] is None
        assert conn.execute('select to_jsonb(k) from knowledge_mastery k where user_id=%s',(owner,)).fetchall()==before
        for index in range(1,121):last=block(index=index)
        page=transcript(bid=last)
        assert page['total']==121 and page['offset']==100 and len(page['blocks'])==21 and page['blocks'][-1]['id']==str(last)
        rejects('42501',lambda:transcript(foreign))
        rejects('42501',lambda:transcript(bid=other_block))
        rejects('22023',lambda:transcript(offset=-1))
        rejects('23503',lambda:conn.execute('update lecture_topic_links set knowledge_point_id=%s where lecture_id=%s',(foreign_topic,lecture['id'])))
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        assert conn.execute('select count(*) from lectures').fetchone()[0]==1
        rejects('42501',lambda:conn.execute("update lectures set title='forged' where id=%s",(lecture['id'],)))
        rejects('42501',lambda:transcript())
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from lectures').fetchone()[0]==0
        assert conn.execute('select count(*) from lecture_topic_links').fetchone()[0]==0
        conn.rollback();print('PASS: audio-only attach/replay, Topic CAS/scope/archive/unlink, stale text alignment, no Mastery change, 121-block pagination/deep link, FK/RLS/private RPC; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY']='localhost,127.0.0.1,::1';os.environ['no_proxy']=os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row=conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row:raise SystemExit('No local subject for API checks')
            app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    assert client.get('/api/v1/lectures',params={'subject_id':str(row[0])}).status_code==200
                    assert client.get('/api/v1/lectures/capabilities').status_code==200
                    assert client.get('/api/v1/lectures/audio-materials',params={'subject_id':str(row[0])}).status_code==200
                    assert client.get('/api/v1/conversions',params={'subject_id':str(row[0])}).status_code==200
                    assert client.get('/api/v1/lectures',params={'subject_id':str(uuid4())}).status_code==404
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/lectures/capabilities').status_code==401
            print('PASS: real local Supabase read-only lecture APIs, foreign subject 404, anonymous 401; test auth override; no audio/model/user writes')


if __name__=='__main__':main()
