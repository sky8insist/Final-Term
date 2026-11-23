"""Local notes migration/transaction/RLS acceptance; fixture rows roll back."""
import argparse
import os
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
        raise SystemExit('Refusing a non-local database')
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        if not conn.execute("select to_regclass('public.artifact_versions')").fetchone()[0]:
            if not args.apply:
                raise SystemExit('Missing 042_notes_versions.sql; use --apply')
            conn.execute((Path(__file__).resolve().parents[1] / 'migrations/042_notes_versions.sql').read_text(encoding='utf-8'))
            conn.commit()
            print('Applied locally: 042_notes_versions.sql')
        elif args.apply:
            migration = (Path(__file__).resolve().parents[1] / 'migrations/042_notes_versions.sql').read_text(encoding='utf-8')
            start = migration.index('create or replace function public.save_note(')
            end = migration.index('revoke all on function', start)
            conn.execute(migration[start:end])
            conn.commit()
            print('Refreshed local save_note function from 042')
        conn.execute("select set_config('request.jwt.claims', '{\"role\":\"service_role\"}', true)")
        owner, foreign, subject, other_subject, material = [uuid4() for _ in range(5)]
        for uid in [owner, foreign]:
            conn.execute('insert into auth.users(id) values(%s)', (uid,))
        for sid, uid in [(subject, owner), (other_subject, foreign)]:
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Notes rollback')", (sid, uid))
        conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'notes.txt','text/plain',10,'ready')", (material, owner, subject))
        block = conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,page_number,sequence_index,parser_name,parser_version,source_hash) values(%s,%s,%s,'paragraph','Canonical eigenvalue definition',7,0,'test','1',%s) returning id", (owner, subject, material, str(uuid4()))).fetchone()[0]
        topic = conn.execute("select (resolve_course_topic(%s,%s,'Eigenvalues')).id", (owner, subject)).fetchone()[0]
        values = {'title': 'Notes acceptance', 'mode': 'standard', 'citationIds': [str(block)], 'topicIds': [str(topic)],
                  'content': {'sections': [{'id': 's1', 'title': 'Definition', 'body': 'Eigenvalue definition', 'citationIds': [str(block)]}]}}
        def save(note_id, version, data):
            return conn.execute('select save_note(%s,%s,%s,%s,%s)', (owner, subject, note_id, version, Jsonb(data))).fetchone()[0]
        first = save(None, None, values)
        note_id = first['id']
        assert first['version'] == 1 and first['citations'][0]['pageNumber'] == 7
        assert first['citations'][0]['chunkText'] == 'Canonical eigenvalue definition'
        assert conn.execute('select count(*) from note_sources where artifact_id=%s', (note_id,)).fetchone()[0] == 1
        assert conn.execute('select count(*) from artifact_topics where artifact_id=%s', (note_id,)).fetchone()[0] == 1
        edited = {**values, 'title': 'Manual edit'}
        second = save(note_id, 1, edited)
        assert second['version'] == 2 and second['is_user_edited']
        for bad_data, expected_code, expected_version in [
            (edited, '40001', 1),
            ({**values, 'citationIds': [str(uuid4())]}, '22023', 2),
            ({**values, 'topicIds': [str(uuid4())]}, '22023', 2),
            ({**values, 'content': {'sections': [{'id': 'x', 'title': 'X', 'body': 'X', 'citationIds': []}]}}, '22023', 2),
        ]:
            try:
                with conn.transaction():
                    save(note_id, expected_version, bad_data)
            except psycopg.Error as exc:
                assert exc.sqlstate == expected_code, exc.sqlstate
            else:
                raise AssertionError('Invalid/conflicting note write accepted')
        assert conn.execute('select count(*) from artifact_versions where artifact_id=%s', (note_id,)).fetchone()[0] == 2
        restored = save(note_id, 2, values)
        assert restored['version'] == 3 and restored['title'] == values['title']
        assert conn.execute('select snapshot->>\'title\' from artifact_versions where artifact_id=%s and version=2', (note_id,)).fetchone()[0] == 'Manual edit'
        try:
            with conn.transaction():
                conn.execute('select save_note(%s,%s,%s,3,%s)', (foreign, subject, note_id, Jsonb(values)))
        except psycopg.errors.InsufficientPrivilege:
            pass
        else:
            raise AssertionError('Cross-owner write accepted')
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        assert conn.execute('select count(*) from artifact_versions where artifact_id=%s', (note_id,)).fetchone()[0] == 3
        assert conn.execute("update artifacts set title='forged' where id=%s returning id", (note_id,)).fetchone() is None
        assert conn.execute('delete from artifact_topics where artifact_id=%s returning artifact_id', (note_id,)).fetchone() is None
        for sql, params in [
            ('update artifact_versions set snapshot=\'{}\' where artifact_id=%s', (note_id,)),
            ('select save_note(%s,%s,%s,3,%s)', (owner, subject, note_id, Jsonb(values))),
            ("insert into artifacts(user_id,subject_id,artifact_type,title,content) values(%s,%s,'notes','forged','{}')", (owner, subject)),
        ]:
            try:
                with conn.transaction():
                    conn.execute(sql, params)
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError('Authenticated direct notes write accepted')
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        for table in ['artifacts', 'artifact_versions', 'note_sources', 'artifact_topics']:
            assert conn.execute(f'select count(*) from {table} where user_id=%s', (owner,)).fetchone()[0] == 0
        conn.rollback()
        print('PASS: canonical source/page, atomic topic/source links, version snapshots, stale CAS rollback, restore as new version, owner/RLS/read-only history; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
                raise SystemExit('Refusing a non-local Supabase URL')
            row = conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row:
                raise SystemExit('N/A: no local subject for API smoke')
            source = conn.execute("select b.id,b.user_id,b.subject_id from content_blocks b join materials m on m.id=b.material_id where b.user_id=m.user_id and b.subject_id=m.subject_id and m.status='ready' order by b.created_at,b.id limit 1").fetchone()
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.models.user import CurrentUser
            from app.main import app
            os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
            os.environ['no_proxy'] = os.environ['NO_PROXY']
            if source:
                from app.services.notes_service import canonical_sources
                citations = canonical_sources(user_id=str(source[1]), subject_id=str(source[2]), block_ids=[str(source[0])])
                assert len(citations) == 1 and citations[0]['id'] == str(source[0])
                print('PASS: actual Supabase private canonical source RPC; owned ready content block')
            else:
                print('N/A: no ready block for actual Supabase source RPC')
            overrides = app.dependency_overrides.copy()
            try:
                with TestClient(app) as client:
                    app.dependency_overrides.pop(get_current_user, None)
                    assert client.get('/api/v1/notes', params={'subject_id': str(row[0])}).status_code == 401
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]), email=None)
                    result = client.get('/api/v1/notes', params={'subject_id': str(row[0])})
                    assert result.status_code == 200, result.status_code
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(uuid4()), email=None)
                    assert client.get('/api/v1/notes', params={'subject_id': str(row[0])}).status_code == 404
                    print('PASS: actual Supabase notes list 200, anonymous 401, cross-owner subject 404 (auth override; read-only)')
            finally:
                app.dependency_overrides.clear()
                app.dependency_overrides.update(overrides)


if __name__ == '__main__':
    main()
