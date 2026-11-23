"""Local DB + real Redis + Supabase/API cache verification across two DB sessions.

Commits disposable users, then deletes only those generated IDs and exact cache keys.
"""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from fastapi import HTTPException
from app.config.settings import settings
from app.services import workspace_cache_service as service


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    for value in (settings.database_url,settings.supabase_url,settings.redis_url):
        if urlparse(value or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local DB/Supabase/Redis required')
    os.environ['NO_PROXY']='localhost,127.0.0.1,::1';os.environ['no_proxy']=os.environ['NO_PROXY']
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        migration=(Path(__file__).resolve().parents[1]/'migrations/054_workspace_cache_versions.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.workspace_cache_versions')").fetchone()[0]:
            if not args.apply:raise SystemExit('Missing 054; use --apply locally')
            conn.execute(migration);conn.commit();print('Applied local 054')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;',migration,re.S):conn.execute(sql.replace('create function','create or replace function',1))
            conn.execute('revoke all on function public.revoke_workspace_snapshots(uuid) from public,anon,authenticated')
            conn.execute('grant execute on function public.revoke_workspace_snapshots(uuid) to service_role')
            conn.execute("notify pgrst,'reload schema'");conn.commit()
        owner,foreign,a,b,c,blueprint,exam,attempt,material=[uuid4() for _ in range(9)]
        keys=set()
        def version(resource='dashboard',scope=None,uid=owner):
            return service.current_version(user_id=str(uid),resource=resource,subject_id=str(scope) if scope else None)
        def save(resource,scope,data):
            value=version(resource,scope)
            key=service._key(user_id=str(owner),resource=resource,subject_id=str(scope) if scope else None,version=value['version']);keys.add(key)
            service.save_snapshot(user_id=str(owner),resource=resource,subject_id=str(scope) if scope else None,data=data,expected_version=value['version'])
            return value
        try:
            for uid in (owner,foreign):conn.execute('insert into auth.users(id) values(%s)',(uid,))
            for sid,uid in ((a,owner),(b,owner),(c,foreign)):
                conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Disposable workspace cache acceptance')",(sid,uid))
            conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery) values(%s,%s,'fixture',.2)",(owner,a))
            conn.execute("insert into exam_blueprints(id,user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,%s,'Fixture',10,10,'{}')",(blueprint,owner,a))
            conn.execute("insert into exams(id,user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,%s,'Fixture',10,10)",(exam,owner,a,blueprint))
            conn.execute("insert into exam_attempts(id,user_id,subject_id,exam_id,expires_at) values(%s,%s,%s,%s,now()+interval '1 hour')",(attempt,owner,a,exam))
            conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'fixture.txt','text/plain',5,'queued')",(material,owner,a))
            conn.commit()
            old=save('dashboard',None,{'synthetic':True,'masteryScore':.2})
            assert service.load_snapshot(user_id=str(owner),resource='dashboard')['data']['masteryScore']==.2
            chat_before=version('chat',a)['dataVersion'];other_before=version('plan',b)['dataVersion'];foreign_before=version(uid=foreign)['dataVersion']
            plan_before=version('plan',a)['dataVersion'];recommend_before=version('recommendations',a)['dataVersion']
            # Another terminal commits grading + mastery. Invalidation occurs inside this transaction.
            with psycopg.connect(settings.database_url,connect_timeout=5) as writer:
                writer.execute("update knowledge_mastery set mastery=.9,attempts=3 where user_id=%s and subject_id=%s",(owner,a))
                writer.execute("update exam_attempts set status='graded',submitted_at=now() where id=%s",(attempt,))
                immediate=writer.execute('select workspace_resource_version(%s,%s,null)',(owner,'dashboard')).fetchone()[0]
                assert immediate['dataVersion']!=old['dataVersion']
            assert version()['dataVersion']!=old['dataVersion']
            assert service.load_snapshot(user_id=str(owner),resource='dashboard') is None
            try:service.save_snapshot(user_id=str(owner),resource='dashboard',data={'synthetic':True,'masteryScore':.2},expected_version=old['version'])
            except HTTPException as exc:assert exc.status_code==409
            else:raise AssertionError('Old writer accepted')
            assert version('chat',a)['dataVersion']==chat_before
            assert version('plan',b)['dataVersion']==other_before and version(uid=foreign)['dataVersion']==foreign_before
            assert version('plan',a)['dataVersion']!=plan_before and version('recommendations',a)['dataVersion']!=recommend_before
            save('dashboard',None,{'synthetic':True,'masteryScore':.9})
            assert service.load_snapshot(user_id=str(owner),resource='dashboard')['data']['masteryScore']==.9
            map_before=version('mind-map',a)['dataVersion']
            conn.execute("update materials set status='ready' where id=%s",(material,));conn.commit()
            assert version('mind-map',a)['dataVersion']!=map_before and version('chat',a)['dataVersion']==chat_before
            save('chat',a,[{'synthetic':True,'content':'Owned fixture'}])
            assert service.load_snapshot(user_id=str(owner),resource='chat',subject_id=str(b)) is None
            try:version('chat',c)
            except HTTPException as exc:assert exc.status_code==404
            else:raise AssertionError('Foreign subject accepted')
            revoke_before=version('workspace')['version']
            service.reset_user_snapshots(user_id=str(owner))
            assert version('workspace')['version']!=revoke_before
            assert all(not service.get_redis_client().exists(key) for key in keys)
            save('chat',b,[{'synthetic':True,'content':'Revocation fixture'}])
            original_redis=service.get_redis_client
            def unavailable_redis():
                from redis.exceptions import ConnectionError
                raise ConnectionError('Fixture offline')
            try:
                service.get_redis_client=unavailable_redis
                service.reset_user_snapshots(user_id=str(owner))
            finally:service.get_redis_client=original_redis
            assert service.load_snapshot(user_id=str(owner),resource='chat',subject_id=str(b)) is None
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            app.dependency_overrides[get_current_user]=lambda:CurrentUser(id=str(owner))
            try:
                with TestClient(app) as client:
                    response=client.get('/api/v1/workspace/cache/dashboard/version');assert response.status_code==200,response.text
                    assert response.headers['cache-control']=='no-store'
                    assert client.get('/api/v1/workspace/cache/chat/version',params={'subjectId':str(c)}).status_code==404
                    assert client.get('/api/v1/workspace/cache/chat/version').status_code==422
                    assert client.get('/api/v1/workspace/cache/dashboard',params={'subjectId':str(a)}).status_code==422
                    assert client.get('/api/v1/workspace/cache/dashboard').status_code==404  # indexed material invalidated dashboard
            finally:app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:assert client.get('/api/v1/workspace/cache/dashboard/version').status_code==401
            conn.execute('set local role authenticated');conn.execute("select set_config('request.jwt.claims','{}',true)")
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
            assert conn.execute('select count(*) from workspace_cache_versions where user_id=%s',(owner,)).fetchone()[0]==0
            try:
                with conn.transaction():conn.execute('select workspace_resource_version(%s,%s,null)',(owner,'dashboard'))
            except psycopg.Error as exc:assert exc.sqlstate=='42501'
            else:raise AssertionError('Public RPC accepted')
            conn.execute('reset role');conn.rollback()
            print('PASS: real Redis + actual Supabase versions/cache + separate DB writer; grading/mastery invalidates immediately before worker, stale GET/PUT rejected, fresh .9 replaces .2, resource/subject/user precision, material/map invalidation, API no-store/401/404/422, RLS/private RPC')
        finally:
            conn.rollback()
            for uid in (owner,foreign):conn.execute('delete from auth.users where id=%s',(uid,))
            conn.commit()
            if keys:service.get_redis_client().delete(*keys)
            print('CLEANUP: exact disposable users/data and test Redis keys removed; real user snapshots untouched')


if __name__=='__main__':main()
