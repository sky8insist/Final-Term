"""Local committed disposable fixtures, normal password auth and real HTTP API.

No identity overrides, model calls, or existing-user writes. --apply installs 058.
SQL rollback injection is a separate transaction test, not a real service outage.
"""
import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
import psycopg
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services.privacy_service import USER_TABLES
from app.services.workspace_cache_service import get_redis_client


def seed(conn, owner, count=1):
    subject, topic, blueprint, exam, question = [uuid4() for _ in range(5)]
    conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Privacy fixture')", (subject, owner))
    conn.execute("insert into knowledge_points(id,user_id,subject_id,knowledge_key,title) values(%s,%s,%s,'privacy','Private topic')", (topic, owner, subject))
    conn.execute("insert into profiles(id,username) values(%s,%s)", (owner, 'p'+uuid4().hex[:20]))
    conn.execute("insert into dayend_runs(run_id,thread_id,user_id,status,state_json) values(%s,%s,%s,'completed','{}')", (str(uuid4()), str(uuid4()), owner))
    conn.execute("insert into dayend_night_states(thread_id,user_id,closure_json) values(%s,%s,'{}')", (str(uuid4()), owner))
    conn.execute("insert into security_events(user_id,event_type,severity) values(%s,'privacy-fixture','info')", (owner,))
    conn.execute("insert into memory_entries(user_id,target,content,content_hash) values(%s,'assistant_memory','I prefer concise explanations',%s)", (owner, uuid4().hex))
    conn.execute("insert into memory_snapshots(user_id,session_id) values(%s,%s)", (owner, uuid4()))
    conn.execute("insert into exam_blueprints(id,user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,%s,'Privacy',10,10,'{}')", (blueprint, owner, subject))
    conn.execute("insert into exams(id,user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,%s,'Privacy',10,10)", (exam, owner, subject, blueprint))
    conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,'privacy','single_choice','medium')", (question, owner, subject))
    conn.execute("insert into question_versions(question_id,version,stem,correct_answer,explanation) values(%s,1,'fixture','\"A\"','fixture')", (question,))
    section = conn.execute("insert into exam_sections(exam_id,title,sequence_index,points) values(%s,'fixture',0,1) returning id", (exam,)).fetchone()[0]
    conn.execute("insert into exam_questions(exam_id,section_id,question_id,question_version,sequence_index,points) values(%s,%s,%s,1,0,1)", (exam, section, question))
    conn.execute("insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version) select %s,%s,'step.completed','privacy-fixture',gen_random_uuid(),i::text,'fixture' from generate_series(1,%s) i", (owner, subject, count))
    conn.commit()
    return subject


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT.parent/'docs/acceptance/privacy_integrity_20261027/report.json')
    args = parser.parse_args()
    for value in (settings.database_url, settings.supabase_url, settings.redis_url):
        if urlparse(value or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise SystemExit('Only local DB/Auth/Redis allowed')
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'
    report = {'startedAt': datetime.now(UTC).isoformat(), 'mode': 'real local HTTP/password/JWT; no overrides',
              'data': 'disposable synthetic fixtures', 'checks': [], 'cleanup': False,
              'limitations': ['no browser UI or production acceptance', 'no live LightRAG/model call',
                              'no concurrent upload/worker deletion fence', 'JSON export includes metadata, not original binary files',
                              'Auth/operational service logs and backups retain their own policies']}
    users, paths = [], []
    client = get_supabase_client()
    process = None
    def passed(name):
        report['checks'].append({'name': name, 'status': 'passed'})
        print('PASS: '+name, flush=True)
    with psycopg.connect(settings.database_url) as conn, tempfile.TemporaryDirectory(prefix='privacy-', dir=ROOT) as temp:
        try:
            if args.apply:
                conn.execute((ROOT/'migrations/058_privacy_integrity.sql').read_text(encoding='utf-8'))
                conn.commit()
                print('Applied local migration 058', flush=True)
                time.sleep(.5)
            if not conn.execute("select to_regprocedure('export_privacy_bundle(uuid)')").fetchone()[0]:
                raise RuntimeError('Migration 058 required')
            creds = []
            for _ in range(3):
                email, password = 'privacy-'+uuid4().hex+'@example.test', secrets.token_urlsafe(24)
                user = client.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True}).user.id
                users.append(user); creds.append((email, password))
            owner, other, direct = users
            subject = seed(conn, owner, 1005)
            seed(conn, other)
            seed(conn, direct)
            # Deferred constraints still reject removal of a referenced question.
            try:
                with conn.transaction():
                    conn.execute('delete from questions where user_id=%s', (owner,))
                    conn.execute('set constraints all immediate')
                raise AssertionError('Referenced question deletion was allowed')
            except psycopg.errors.ForeignKeyViolation:
                pass
            conn.rollback()
            passed('deferred foreign keys still reject deletion of a referenced question')
            # Reproduce the former failing role through the actual Auth admin API.
            client.auth.admin.delete_user(direct)
            assert not conn.execute('select exists(select 1 from auth.users where id=%s)', (direct,)).fetchone()[0]
            passed('real Auth admin cascade with topic, memory and exam fixtures no longer returns 500')
            # Direct admin deletion is not a privacy API: legacy text-ID rows have no FK.
            for table in ('dayend_runs', 'dayend_night_states'):
                conn.execute(f'delete from {table} where user_id=%s', (direct,))
            conn.commit()
            # Inject failure inside SQL transaction, then prove all earlier deletes rolled back.
            try:
                conn.execute("create function public.privacy_fixture_failure() returns trigger language plpgsql as $$begin raise exception 'fixture failure';end$$")
                conn.execute(f"create trigger privacy_fixture_failure before delete on dayend_night_states for each row when(old.user_id='{owner}') execute function public.privacy_fixture_failure()")
                try:
                    with conn.transaction():
                        conn.execute('select delete_privacy_learning_data(%s)', (owner,))
                    raise AssertionError('Expected SQL failure')
                except psycopg.errors.RaiseException:
                    pass
                assert conn.execute('select exists(select 1 from subjects where id=%s)', (subject,)).fetchone()[0]
                assert conn.execute('select count(*) from exams where user_id=%s', (owner,)).fetchone()[0] == 1
                passed('injected SQL failure rolls back subjects, exams and global cleanup atomically')
            finally:
                conn.rollback()
            # Real original audio asset + derived transcript asset, both manifest-tracked.
            material = uuid4()
            conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size) values(%s,%s,%s,'fixture.wav','audio/wav',12)", (material, owner, subject))
            for kind, suffix in (('original','wav'), ('transcript','txt')):
                path = f'{owner}/{subject}/{material}/privacy-fixture.{suffix}'
                client.storage.from_('study-materials').upload(path, b'privacy-fixture', {'content-type': 'application/octet-stream'})
                paths.append(path)
                conn.execute("insert into material_assets(user_id,subject_id,material_id,asset_type,bucket,object_path,content_type,file_size,sha256) values(%s,%s,%s,%s,'study-materials',%s,'application/octet-stream',15,%s)", (owner, subject, material, kind, path, hashlib.sha256(b'privacy-fixture').hexdigest()))
            conn.commit()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            with open(Path(temp)/'api.log', 'w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=60) as http:
                    for _ in range(150):
                        if process.poll() is not None: raise RuntimeError('Isolated API exited')
                        try:
                            if http.get('/openapi.json').status_code==200: break
                        except httpx.HTTPError: pass
                        time.sleep(.2)
                    else: raise RuntimeError('Isolated API not ready')
                    headers = []
                    for email, password in creds[:2]:
                        auth = httpx.post(settings.supabase_url+'/auth/v1/token?grant_type=password',
                            headers={'apikey':settings.supabase_anon_key}, json={'email':email,'password':password}, trust_env=False)
                        assert auth.status_code==200
                        headers.append({'Authorization':'Bearer '+auth.json()['access_token']})
                    endpoint = '/api/v1/privacy'
                    assert http.get(endpoint+'/export').status_code==401
                    assert http.delete(endpoint+'/data?confirm=wrong',headers=headers[0]).status_code==422
                    assert http.delete(endpoint+'/account?confirm=wrong',headers=headers[0]).status_code==422
                    passed('anonymous rejection and destructive confirmation guards over real HTTP')
                    exported = http.get(endpoint+'/export',headers=headers[0]); assert exported.status_code==200
                    assert exported.headers['cache-control']=='no-store'
                    data = exported.json()['data']
                    assert set(USER_TABLES).issubset(data)
                    assert len(data['product_events'])==1005 and len(data['question_versions'])==1
                    assert len(data['profiles'])==1 and len(data['dayend_runs'])==1
                    assert len(data['material_assets'])==2
                    assert all(str(row['user_id'])==owner for rows in data.values() for row in rows if 'user_id' in row)
                    assert data['profiles'][0]['id']==owner
                    report['exportedTables'] = len(data); report['exportedEvents'] = len(data['product_events'])
                    passed('uncapped consistent JSON export: 1005 events, legacy records, profile and owned children; no-store')
                    other_data = http.get(endpoint+'/export',headers=headers[1]).json()['data']
                    assert len(other_data['product_events'])==1
                    assert all(str(row['user_id'])==other for rows in other_data.values() for row in rows if 'user_id' in row)
                    passed('two normally authenticated accounts export only their own data')
                    result = http.delete(endpoint+'/data?confirm=DELETE',headers=headers[0])
                    assert result.status_code==200, result.text
                    remaining = http.get(endpoint+'/export',headers=headers[0]); assert remaining.status_code==200
                    expected = {'profiles','workspace_cache_versions'}
                    assert all(not rows for table, rows in remaining.json()['data'].items() if table not in expected)
                    assert conn.execute('select exists(select 1 from auth.users where id=%s)',(owner,)).fetchone()[0]
                    for path in paths:
                        try: client.storage.from_('study-materials').download(path)
                        except Exception as exc:
                            # A transport outage is not evidence that a file was deleted.
                            if not hasattr(exc, 'status') and not hasattr(exc, 'status_code'):
                                raise
                            assert int(getattr(exc, 'status', getattr(exc, 'status_code', 0))) in (400, 404)
                        else: raise AssertionError('Stored asset still readable')
                    assert http.delete(endpoint+'/data?confirm=DELETE',headers=headers[0]).status_code==200
                    passed('product data deletion removes learning/audit/legacy rows and stored audio/transcript; identity preserved; retry succeeds')
                    # Refill after data reset, then exercise the complete account path.
                    conn.execute('delete from profiles where id=%s',(owner,)); conn.commit()
                    seed(conn, owner)
                    result = http.delete(endpoint+'/account?confirm=DELETE',headers=headers[0])
                    assert result.status_code==200, result.text
                    assert not conn.execute('select exists(select 1 from auth.users where id=%s)',(owner,)).fetchone()[0]
                    assert http.get(endpoint+'/export',headers=headers[0]).status_code==401
                    assert http.get('/api/v1/subjects',headers=headers[0]).status_code==401
                    refresh = httpx.post(settings.supabase_url+'/auth/v1/token?grant_type=password',headers={'apikey':settings.supabase_anon_key},json={'email':creds[0][0],'password':creds[0][1]},trust_env=False)
                    assert refresh.status_code!=200
                    assert len(http.get(endpoint+'/export',headers=headers[1]).json()['data']['product_events'])==1
                    passed('complete product account deletion, old JWT rejected, login rejected and other account unchanged')
                    assert http.delete(endpoint+'/account?confirm=DELETE',headers=headers[1]).status_code==200
                    passed('second populated account also deleted via normal product API')
            conn.rollback()
            assert not conn.execute("select has_function_privilege('authenticated','export_privacy_bundle(uuid)','execute')").fetchone()[0]
            assert not conn.execute("select has_function_privilege('anon','delete_privacy_learning_data(uuid)','execute')").fetchone()[0]
            passed('privacy RPCs remain private to service_role')
        except Exception as exc:
            report['failureType'] = type(exc).__name__
            raise
        finally:
            if process is not None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            conn.rollback()
            # Finally cleanup is not evidence that the product delete passed.
            if paths: client.storage.from_('study-materials').remove(paths)
            for user in users:
                for table in ('dayend_runs','dayend_night_states'):
                    conn.execute(f'delete from {table} where user_id=%s',(user,))
                if conn.execute('select exists(select 1 from auth.users where id=%s)', (user,)).fetchone()[0]:
                    conn.execute('select delete_privacy_learning_data(%s)', (user,))
                    conn.execute('delete from auth.users where id=%s',(user,))
                redis = get_redis_client()
                for namespace in ('v1','v2'):
                    keys = list(redis.scan_iter(match=f'workspace:{namespace}:{user}:*'))
                    if keys: redis.delete(*keys)
            conn.commit()
            report['cleanup'] = all(not conn.execute('select exists(select 1 from auth.users where id=%s)',(u,)).fetchone()[0] for u in users)
            report['finishedAt'] = datetime.now(UTC).isoformat()
            report['success'] = 'failureType' not in report and len(report['checks']) == 10 and report['cleanup']
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Report saved; disposable accounts cleaned',flush=True)


if __name__=='__main__': main()
