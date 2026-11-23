"""Local rollback acceptance for structural annotations and canonical chunk sources."""
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings
from app.services.chunk_service import build_structure_chunk_bundle
from app.services.document_structure_service import enrich_document_structure


def main():
    if urlparse(settings.database_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Local database required')
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        owner, foreign, subject, material = [uuid4() for _ in range(4)]
        for uid in (owner, foreign): conn.execute('insert into auth.users(id) values(%s)', (uid,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Structure rollback')", (subject, owner))
        conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'fixture.pdf','application/pdf',1,'ready')", (material, owner, subject))
        original = [{'id': str(uuid4()), 'block_type': kind, 'content_text': text,
                     'sequence_index': index, 'page_number': 1, 'source_hash': f'fixture-{index}',
                     'metadata': {}, 'structured_data': {}, 'confidence': None}
                    for index, (kind, text) in enumerate([('image', 'Diagram ' * 20), ('paragraph', 'Figure 1: Model')])]
        blocks, report = enrich_document_structure(original)
        assert report['adjacentCaptions'] == 1 and report['unknownConfidence'] == 2
        for row in blocks:
            conn.execute("insert into content_blocks(id,user_id,subject_id,material_id,block_type,content_text,sequence_index,page_number,parser_name,parser_version,source_hash,confidence,metadata) values(%s,%s,%s,%s,%s,%s,%s,%s,'fixture','1',%s,%s,%s)",
                (row['id'], owner, subject, material, row['block_type'], row['content_text'], row['sequence_index'], row['page_number'], row['source_hash'], row['confidence'], Jsonb(row['metadata'])))
        bundle = build_structure_chunk_bundle(blocks, chunk_size=50, overlap=10, parent_size=100)
        assert len(bundle['parents']) == 1
        conn.execute('select replace_material_chunk_bundle(%s,%s,%s,%s,%s,%s)',
            (owner, subject, material, 'structure', Jsonb(bundle['parents']), Jsonb(bundle['records'])))
        assert conn.execute('select strategy_version from parent_chunks where material_id=%s', (material,)).fetchone()[0] == 'structure-v2'
        annotation = conn.execute("select metadata->'documentStructure' from material_chunks where material_id=%s and chunk_index=0", (material,)).fetchone()[0]
        assert annotation['relations'][0]['sourceHash'] == blocks[1]['source_hash']
        assert conn.execute('select status from materials where id=%s', (material,)).fetchone()[0] == 'parsing'
        conn.execute("update materials set status='ready' where id=%s", (material,))
        citations = conn.execute('select note_source_citations(%s,%s,%s)', (owner, subject, [row['id'] for row in blocks])).fetchone()[0]
        assert {row['id'] for row in citations} == {row['id'] for row in blocks}
        assert conn.execute('select confidence from content_blocks where id=%s', (blocks[0]['id'],)).fetchone()[0] is None
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        assert conn.execute('select count(*) from parent_chunks').fetchone()[0] == 1
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert conn.execute('select count(*) from material_chunks').fetchone()[0] == 0
        assert conn.execute('select count(*) from content_blocks').fetchone()[0] == 0
        conn.rollback()
        print('PASS: caption parent retention, v2 parent/child metadata, nullable confidence, canonical source IDs, owner/foreign RLS; fixtures rolled back; no model or external parser calls')


if __name__ == '__main__': main()
