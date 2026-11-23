"""Local upload Notes SQL/API acceptance; fixtures roll back, no model/broker calls."""
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
        migration = (Path(__file__).resolve().parents[1] / 'migrations/048_upload_notes.sql').read_text(encoding='utf-8')
        present = conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name='materials' and column_name='upload_notes_mode')").fetchone()[0]
        if not present:
            if not args.apply: raise SystemExit('Missing 048; use --apply locally')
            conn.execute(migration); conn.commit(); print('Applied local 048')
        elif args.apply:
            for sql in re.findall(r'create (?:or replace )?function .*?\$\$;', migration, re.S):
                conn.execute(sql.replace('create function', 'create or replace function', 1))
            conn.execute("notify pgrst,'reload schema'"); conn.commit(); print('Refreshed local upload Notes functions')
        conn.execute("select set_config('request.jwt.claims','{\"role\":\"service_role\"}',true)")
        owner, foreign, subject, mid = [uuid4() for _ in range(4)]
        for uid in (owner, foreign): conn.execute('insert into auth.users(id) values(%s)', (uid,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Upload Notes rollback')", (subject, owner))
        conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'notes.txt','text/plain',5,'queued')", (mid, owner, subject))
        def rejects(code, operation):
            try:
                with conn.transaction(): operation()
            except psycopg.Error as exc: assert exc.sqlstate == code, str(exc)
            else: raise AssertionError(f'Expected {code}')
        def configure(mode='standard', uid=owner):
            return conn.execute('select configure_upload_notes(%s,%s,%s)', (uid, mid, mode)).fetchone()[0]
        def transition(action, conversion=None, uid=owner):
            return conn.execute('select transition_upload_notes(%s,%s,%s,%s)', (uid, mid, action, conversion)).fetchone()[0]
        def summary():
            return next(row for row in conn.execute('select material_processing_summary(%s,%s)', (owner, subject)).fetchone()[0] if row['materialId'] == str(mid))
        def pending(): return conn.execute('select pending_upload_notes()').fetchone()[0]
        assert summary()['notes'] is None
        rejects('23514', lambda: conn.execute('update materials set upload_notes_request_id=%s where id=%s', (uuid4(), mid)))
        rejects('42501', lambda: configure(uid=foreign))
        saved = configure()
        request = saved['upload_notes_request_id']
        assert configure()['upload_notes_request_id'] == request
        rejects('40001', lambda: configure('summary'))
        assert summary()['notes']['status'] == 'waiting_material'
        assert transition('start') is None
        conn.execute("update materials set status='ready' where id=%s", (mid,))
        assert any(row['id'] == str(mid) for row in pending())
        assert transition('start')['upload_notes_attempts'] == 1
        assert transition('start') is None
        rejects('40001', lambda: transition('reset'))
        transition('error')
        assert summary()['notes']['status'] == 'enqueue_failed' and summary()['notes']['canRetry']
        for _ in range(2):
            conn.execute("update materials set upload_notes_retry_at=now()-interval '1 minute' where id=%s", (mid,))
            transition('start'); transition('error')
        assert conn.execute('select upload_notes_attempts from materials where id=%s', (mid,)).fetchone()[0] == 3
        assert not any(row['id'] == str(mid) for row in pending())
        assert transition('start') is None
        transition('reset'); transition('start')
        rejects('22023', lambda: transition('done', uuid4()))
        block = conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,sequence_index,parser_name,parser_version,source_hash) values(%s,%s,%s,'paragraph','Canonical Notes source',0,'fixture','1',%s) returning id", (owner, subject, mid, str(uuid4()))).fetchone()[0]
        citations = conn.execute('select note_source_citations(%s,%s,%s)', (owner, subject, [block])).fetchone()[0]
        source = {'kind': 'material', 'id': str(mid)}
        snapshot = {'source': source, 'title': 'notes.txt', 'content': {}, 'topicIds': [], 'citations': citations, 'warnings': []}
        def enqueue():
            return conn.execute('select enqueue_conversion(%s,%s,%s,%s,%s,%s,%s,%s)',
                (owner, subject, request, 'upload-note-fingerprint', Jsonb(source), 'notes', Jsonb({'count': 10, 'mode': 'standard'}), Jsonb(snapshot))).fetchone()[0]
        job = enqueue()
        # The insert trigger acknowledges before Python can mark or dispatch it.
        assert conn.execute('select upload_notes_dispatched from materials where id=%s', (mid,)).fetchone()[0]
        assert enqueue()['id'] == job['id']
        assert transition('done', job['id'])['upload_notes_dispatched']
        assert not any(row['id'] == str(mid) for row in pending())
        assert summary()['notes']['status'] == 'queued'
        claim = conn.execute('select claim_conversion(%s)', (job['id'],)).fetchone()[0]
        draft = {'title': 'Upload Notes', 'content': {'sections': [{'id': 's1', 'title': 'Source', 'body': 'Canonical Notes source', 'citationIds': [str(block)]}]}}
        result = conn.execute('select finish_conversion(%s,%s,%s)', (job['id'], claim['claim_token'], Jsonb(draft))).fetchone()[0]
        again = conn.execute('select finish_conversion(%s,%s,%s)', (job['id'], claim['claim_token'], Jsonb(draft))).fetchone()[0]
        assert result['result_artifact_id'] == again['result_artifact_id']
        assert conn.execute('select count(*) from artifact_versions where artifact_id=%s', (result['result_artifact_id'],)).fetchone()[0] == 1
        assert summary()['notes']['status'] == 'succeeded' and summary()['notes']['href'].startswith('/notes?')
        assert conn.execute('select count(*) from topic_coverage where user_id=%s', (owner,)).fetchone()[0] == 0
        conn.execute('delete from artifacts where id=%s', (result['result_artifact_id'],))
        assert summary()['notes']['status'] == 'removed'
        assert transition('start') is None
        rejects('40001', lambda: transition('reset'))
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        rejects('42501', configure)
        rejects('42501', pending)
        rejects('42501', lambda: transition('start'))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert conn.execute('select count(*) from materials').fetchone()[0] == 0
        conn.rollback()
        print('PASS: default opt-out, paired configuration/scope/replay/mode conflict, ready gate/lease/bounded retries/reset, atomic intent acknowledgement, conversion dedup/publish/history, result deletion without regeneration, no coverage writes, private RPC/RLS; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}: raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'; os.environ['no_proxy'] = os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row = conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row: raise SystemExit('No local subject')
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]))
            try:
                with TestClient(app) as client:
                    response = client.get('/api/v1/materials/processing', params={'subject_id': str(row[0])})
                    assert response.status_code == 200, response.text
                    assert all('notes' in item for item in response.json())
                    assert client.get('/api/v1/materials/processing', params={'subject_id': str(uuid4())}).status_code == 404
            finally: app.dependency_overrides.pop(get_current_user, None)
            with TestClient(app) as client:
                assert client.get('/api/v1/materials/processing', params={'subject_id': str(row[0])}).status_code == 401
            print('PASS: real local Supabase bulk status read, foreign 404/anonymous 401; authentication override; no model/broker/user uploads')


if __name__ == '__main__': main()
