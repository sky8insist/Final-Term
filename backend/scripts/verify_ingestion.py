"""Local material recovery acceptance. Fixtures roll back; no uploads/model calls."""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from app.config.settings import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--api', action='store_true')
    args = parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Local database required')
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        present = conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name='materials' and column_name='material_purpose')").fetchone()[0]
        if not present:
            if not args.apply:
                raise SystemExit('Missing migration 046; run --apply locally')
            conn.execute((Path(__file__).resolve().parents[1] / 'migrations/046_material_purpose_recovery.sql').read_text(encoding='utf-8'))
            conn.commit()
            print('Applied local migration 046')
        owner, foreign, subject, other_subject = [uuid4() for _ in range(4)]
        for uid in (owner, foreign):
            conn.execute('insert into auth.users(id) values(%s)', (uid,))
        for sid, uid in ((subject, owner), (other_subject, foreign)):
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Material rollback')", (sid, uid))

        def rejects(code, operation):
            try:
                with conn.transaction(): operation()
            except psycopg.Error as error:
                assert error.sqlstate == code, error.sqlstate
            else:
                raise AssertionError(f'Expected {code}')

        def material(purpose=None, digest=None):
            if purpose is None:
                return conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status,source_hash) values(%s,%s,'notes.txt','text/plain',5,'failed',%s) returning id,material_purpose", (owner, subject, digest)).fetchone()
            return conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status,material_purpose,source_hash) values(%s,%s,'notes.txt','text/plain',5,'failed',%s,%s) returning id,material_purpose", (owner, subject, purpose, digest)).fetchone()

        mid, purpose = material()
        assert purpose == 'learning'
        assert material('syllabus')[1] == 'syllabus'
        assert material('reference')[1] == 'reference'
        rejects('23514', lambda: material('invalid'))
        jid = conn.execute("insert into processing_tasks(user_id,subject_id,material_id,idempotency_key,status,stage,attempts,max_attempts,metadata) values(%s,%s,%s,%s,'failed','failed',3,3,'{\"failedStage\":\"embedding\",\"mineru\":{\"batchId\":\"saved\"}}') returning id", (owner, subject, mid, str(uuid4()))).fetchone()[0]
        def summary(uid=owner, sid=subject):
            return conn.execute('select material_processing_summary(%s,%s)', (uid, sid)).fetchone()[0]
        def retry(uid=owner):
            return conn.execute('select retry_material_ingestion(%s,%s)', (uid, jid)).fetchone()[0]
        def dispatch():
            return conn.execute('select fail_material_dispatch(%s,%s)', (owner, jid)).fetchone()[0]
        assert summary(foreign) == [] and summary(owner, other_subject) == []
        assert next(row for row in summary() if row['materialId'] == str(mid))['sourceAvailable'] is False
        rejects('42501', lambda: retry(foreign))
        rejects('22023', retry)
        assert conn.execute('select status,attempts from processing_tasks where id=%s', (jid,)).fetchone() == ('failed', 3)
        aid = conn.execute("insert into material_assets(user_id,subject_id,material_id,asset_type,bucket,object_path,content_type,file_size,sha256,expires_at) values(%s,%s,%s,'original','private',%s,'text/plain',5,'hash',now()-interval '1 day') returning id", (owner, subject, mid, str(uuid4()))).fetchone()[0]
        rejects('22023', retry)
        conn.execute("update material_assets set expires_at=now()+interval '1 day' where id=%s", (aid,))
        retried = retry()
        assert retried['status'] == 'queued' and retried['attempts'] == 0
        assert retried['metadata']['previousAttempts'] == 3 and retried['metadata']['manualRetryCount'] == 1
        assert retried['metadata']['mineru']['batchId'] == 'saved'
        assert conn.execute('select status from materials where id=%s', (mid,)).fetchone()[0] == 'queued'
        rejects('40001', retry)
        failed = dispatch()
        assert failed['status'] == 'failed' and failed['error_code'] == 'dispatch_failed'
        assert failed['metadata']['failedStage'] == 'queued'
        assert conn.execute('select status from materials where id=%s', (mid,)).fetchone()[0] == 'failed'
        assert dispatch()['status'] == 'failed'
        retry()
        conn.execute("update processing_tasks set status='running',stage='parsing' where id=%s", (jid,))
        assert dispatch()['status'] == 'running'
        conn.execute("update processing_tasks set status='failed' where id=%s", (jid,))
        conn.execute("update materials set status='failed',source_hash='same-file' where id=%s", (mid,))
        duplicate, _ = material(digest='same-file')
        conn.execute("update materials set status='ready' where id=%s", (duplicate,))
        rejects('23505', retry)
        assert conn.execute('select status from processing_tasks where id=%s', (jid,)).fetchone()[0] == 'failed'
        rows = summary()
        assert len(rows) == 4 and len({row['materialId'] for row in rows}) == 4
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        assert conn.execute('select count(*) from materials').fetchone()[0] == 4
        rejects('42501', summary)
        rejects('42501', retry)
        rejects('42501', dispatch)
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert conn.execute('select count(*) from materials').fetchone()[0] == 0
        conn.rollback()
        print('PASS: purpose/default/constraint, latest task summary/scope, missing/expired source, bounded manual retry cycle, replay conflict, broker failure, running acknowledgement, unique hash rollback, RLS/private RPC; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
                raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
            os.environ['no_proxy'] = os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row = conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row: raise SystemExit('No local subject for read-only API check')
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    response = client.get('/api/v1/materials', params={'subject_id': str(row[0])})
                    assert response.status_code == 200, response.text
                    assert all(item['materialPurpose'] in {'learning', 'syllabus', 'reference'} for item in response.json())
                    response = client.get('/api/v1/materials/processing', params={'subject_id': str(row[0])})
                    assert response.status_code == 200, response.text
                    assert client.get('/api/v1/materials/processing', params={'subject_id': str(uuid4())}).status_code == 404
            finally:
                app.dependency_overrides.pop(get_current_user, None)
            with TestClient(app) as client:
                assert client.get('/api/v1/materials/processing', params={'subject_id': str(row[0])}).status_code == 401
            print('PASS: real local Supabase material/processing API reads, foreign 404, anonymous 401; test authentication override; no model/broker/user-data writes')


if __name__ == '__main__':
    main()
