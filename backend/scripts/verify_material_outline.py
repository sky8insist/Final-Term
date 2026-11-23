"""Local SQL outline acceptance; all content fixtures are rolled back."""
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
from app.services.material_outline_service import split_sections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--api', action='store_true')
    args = parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Local database required')
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        if not conn.execute("select to_regclass('public.material_outlines')").fetchone()[0]:
            if not args.apply: raise SystemExit('Missing 047; use --apply locally')
            conn.execute((Path(__file__).resolve().parents[1] / 'migrations/047_material_topic_proposals.sql').read_text(encoding='utf-8'))
            conn.commit(); print('Applied local 047')
        elif args.apply:
            migration = (Path(__file__).resolve().parents[1] / 'migrations/047_material_topic_proposals.sql').read_text(encoding='utf-8')
            for sql in re.findall(r'create function .*?\$\$;', migration, re.S):
                conn.execute(sql.replace('create function', 'create or replace function', 1))
            conn.execute("notify pgrst,'reload schema'"); conn.commit(); print('Refreshed local outline functions')
        conn.execute("select set_config('request.jwt.claims','{\"role\":\"service_role\"}',true)")
        owner, foreign, subject, other_subject = [uuid4() for _ in range(4)]
        for uid in (owner, foreign): conn.execute('insert into auth.users(id) values(%s)', (uid,))
        for sid, uid in ((subject, owner), (other_subject, foreign)):
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Outline rollback')", (sid, uid))
        mid = conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,'outline.txt','text/plain',1,'ready') returning id", (owner, subject)).fetchone()[0]
        def rejects(code, operation):
            try:
                with conn.transaction(): operation()
            except psycopg.Error as exc: assert exc.sqlstate == code, str(exc)
            else: raise AssertionError(f'Expected SQLSTATE {code}')
        ids = []
        for index, (kind, text, level) in enumerate([
            ('paragraph', 'Preamble', 1), ('heading', 'Chapter One', 1),
            ('paragraph', 'Evidence body', 1), ('heading', 'Attention', 2),
            ('paragraph', 'Attention body', 1), ('heading', 'Chapter Two', 1),
        ]):
            ids.append(conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,sequence_index,parser_name,parser_version,source_hash,metadata) values(%s,%s,%s,%s,%s,%s,'fixture','1',%s,%s) returning id", (owner, subject, mid, kind, text, index, str(uuid4()), Jsonb({'headingLevel': level}))).fetchone()[0])
        def snapshot(): return conn.execute('select material_outline_snapshot(%s,%s)', (owner, mid)).fetchone()[0]
        def prepare(blocks=None, sections=None, uid=owner):
            blocks = snapshot() if blocks is None else blocks
            return conn.execute('select prepare_material_outline(%s,%s,%s,%s)', (uid, mid, Jsonb(blocks), Jsonb(split_sections(blocks) if sections is None else sections))).fetchone()[0]
        def read(): return conn.execute('select read_material_outline(%s,%s)', (owner, mid)).fetchone()[0]
        batch = prepare()
        assert len(batch['sections']) == 4 and len(batch['proposals']) == 3 and not batch['stale']
        assert conn.execute('select count(*) from knowledge_points where user_id=%s', (owner,)).fetchone()[0] == 0
        assert prepare()['id'] == batch['id']
        rejects('42501', lambda: prepare(uid=foreign))
        forged = split_sections(snapshot()); forged[1]['blockIds'].pop()
        rejects('22023', lambda: prepare(sections=forged))
        stale_snapshot = snapshot(); stale_snapshot[0]['content_text'] = 'forged'
        rejects('40001', lambda: prepare(blocks=stale_snapshot))
        def decide(proposal, action='accept', version=1, uid=owner, title=None):
            return conn.execute('select decide_material_topic(%s,%s,%s,%s,%s)', (uid, proposal['id'], version, action, title)).fetchone()[0]
        first, second, third = batch['proposals']
        rejects('42501', lambda: decide(first, uid=foreign))
        rejects('40001', lambda: decide(first, version=9))
        accepted = decide(first)
        assert accepted['status'] == 'accepted' and accepted['version'] == 2
        assert decide(first)['knowledge_point_id'] == accepted['knowledge_point_id']
        assert decide(second, title='Self Attention')['status'] == 'accepted'
        assert conn.execute('select count(*) from knowledge_units where user_id=%s', (owner,)).fetchone()[0] == 1
        assert decide(third, 'reject')['status'] == 'rejected'
        assert prepare()['proposals'][2]['status'] == 'rejected'
        rejects('40001', lambda: decide(third))
        assert conn.execute('select count(*) from topic_coverage where user_id=%s', (owner,)).fetchone()[0] == 0
        conn.execute("update content_blocks set content_text='Changed body' where id=%s", (ids[2],))
        assert read()['stale']
        rejects('40001', lambda: decide(first))
        new_batch = prepare()
        assert new_batch['id'] != batch['id'] and not new_batch['stale']
        # Alias reuse preserves user metadata and stable identity.
        new_first = new_batch['proposals'][0]
        assert decide(new_first)['knowledge_point_id'] == accepted['knowledge_point_id']
        conn.execute("update content_blocks set content_text='Evidence body' where id=%s", (ids[2],))
        restored = prepare()
        assert restored['id'] == batch['id'] and restored['proposals'][2]['status'] == 'rejected'
        conn.execute("update content_blocks set content_text='Changed body' where id=%s", (ids[2],))
        assert prepare()['id'] == new_batch['id']
        conn.execute('update knowledge_points set archived=true where id=%s', (accepted['knowledge_point_id'],))
        conn.execute("update content_blocks set content_text='Again' where id=%s", (ids[2],))
        fresh = prepare()
        rejects('22023', lambda: decide(fresh['proposals'][0]))
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        assert conn.execute('select count(*) from material_outlines').fetchone()[0] == 3
        rejects('42501', read)
        rejects('42501', lambda: conn.execute("update material_topic_proposals set status='accepted'"))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert conn.execute('select count(*) from material_topic_proposals').fetchone()[0] == 0
        conn.execute('reset role')
        conn.execute('delete from materials where id=%s', (mid,))
        assert conn.execute('select count(*) from material_outlines where material_id=%s', (mid,)).fetchone()[0] == 0
        assert conn.execute('select count(*) from material_topic_proposals where material_id=%s', (mid,)).fetchone()[0] == 0
        conn.rollback()
        print('PASS: full section partition, evidence snapshots, idempotent prepare, alias/unit reuse, decision CAS/replay/reject, stale body, archived Topic rollback, no coverage writes, RLS/private RPC; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}: raise SystemExit('Local Supabase required')
            os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'; os.environ['no_proxy'] = os.environ['NO_PROXY']
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            row = conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row: raise SystemExit('No local subject')
            material = conn.execute('select id from materials where subject_id=%s and user_id=%s limit 1', (row[0], row[1])).fetchone()
            if not material: raise SystemExit('No local material')
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]))
            url = f'/api/v1/materials/{material[0]}/outline'
            try:
                with TestClient(app) as client:
                    response = client.get(url, params={'subject_id': str(row[0])})
                    assert response.status_code == 200, response.text
                    assert client.get(url, params={'subject_id': str(uuid4())}).status_code == 404
            finally: app.dependency_overrides.pop(get_current_user, None)
            with TestClient(app) as client:
                assert client.get(url, params={'subject_id': str(row[0])}).status_code == 401
            print('PASS: real local Supabase outline read API, foreign 404/anonymous 401; authentication override; no user-data writes')


if __name__ == '__main__': main()
