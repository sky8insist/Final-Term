"""Local-only atomic chunk bundle and scoped parent-context rollback acceptance."""
import argparse
import sys
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings
from app.services.chunk_service import build_block_chunk_records, build_structure_chunk_bundle


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true"); parser.add_argument("--api", action="store_true")
    args = parser.parse_args(); url = settings.database_url or ""
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}: raise SystemExit("Refusing a non-local database")
    with psycopg.connect(url, connect_timeout=5) as conn:
        if not conn.execute("select to_regclass('public.parent_chunks')").fetchone()[0]:
            if not args.apply: raise SystemExit("Missing 040_parent_child_chunks.sql; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "040_parent_child_chunks.sql").read_text(encoding="utf-8")); conn.commit()
            print("Applied locally: 040_parent_child_chunks.sql")
        if not conn.execute("select position('child-evidence-v1' in prosrc)>0 from pg_proc where oid='public.search_content_blocks(text,uuid,uuid,uuid[],text[],double precision,integer)'::regprocedure").fetchone()[0]:
            if not args.apply: raise SystemExit("Missing 041_child_keyword_retrieval.sql; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "041_child_keyword_retrieval.sql").read_text(encoding="utf-8")); conn.commit()
            print("Applied locally: 041_child_keyword_retrieval.sql")
        conn.execute("notify pgrst, 'reload schema'"); conn.commit()
        owner, foreign, subject, material = [uuid4() for _ in range(4)]
        for user in [owner, foreign]: conn.execute("insert into auth.users(id) values(%s)", (user,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Parent child rollback')", (subject, owner))
        conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'chunks.txt','text/plain',1,'parsing')", (material, owner, subject))
        blocks = []
        for i, (kind, text) in enumerate([("heading", "Matrix section"), ("paragraph", "Explanation of eigenvalues."), ("formula", "Ax = lambda x"), ("paragraph", "lambda is an eigenvalue.")]):
            bid = conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,page_number,sequence_index,parser_name,parser_version,source_hash,confidence) values(%s,%s,%s,%s,%s,%s,%s,'test','1',%s,0.9) returning id", (owner, subject, material, kind, text, i + 1, i, str(uuid4()))).fetchone()[0]
            blocks.append({"id": str(bid), "content_text": text, "block_type": kind, "sequence_index": i})
        bundle = build_structure_chunk_bundle(blocks)
        def replace(value, strategy="structure"):
            return conn.execute("select replace_material_chunk_bundle(%s,%s,%s,%s,%s,%s)", (owner, subject, material, strategy, Jsonb(value["parents"]), Jsonb(value["records"]))).fetchone()[0]
        saved = replace(bundle)
        assert len(saved) == 4 and all(row["parent_chunk_id"] == bundle["parents"][0]["id"] for row in saved)
        assert conn.execute("select count(*) from parent_chunk_blocks where material_id=%s", (material,)).fetchone()[0] == 4
        invalid = deepcopy(bundle); invalid["records"][-1]["content_block_id"] = str(uuid4())
        try:
            with conn.transaction(): replace(invalid)
        except psycopg.errors.InsufficientPrivilege: pass
        else: raise AssertionError("Invalid member accepted")
        assert conn.execute("select id from material_chunks where material_id=%s order by chunk_index", (material,)).fetchall() == [(UUID(row["id"]),) for row in saved]
        conn.execute("update materials set status='ready' where id=%s", (material,))
        contexts = conn.execute("select parent_context_blocks(%s,%s,%s)", (owner, subject, [blocks[2]["id"]])).fetchone()[0]
        assert len(contexts) == 4 and any("eigenvalue" in row["text"] for row in contexts)
        hits = conn.execute("select content_text,structured_data from search_content_blocks('eigenvalue',%s,%s)", (owner, subject)).fetchall()
        assert hits and all(row[1].get("retrievalChunkId") and row[1].get("parentChunkId") for row in hits)
        assert conn.execute("select parent_context_blocks(%s,%s,%s)", (foreign, subject, [blocks[2]["id"]])).fetchone()[0] == []
        assert conn.execute("select parent_context_blocks(%s,%s,%s)", (owner, uuid4(), [blocks[2]["id"]])).fetchone()[0] == []
        print("PASS: atomic parent/child replacement, invalid-child rollback, canonical multi-page parent context and owner/subject scope")
        conn.execute("set local role authenticated"); conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        assert conn.execute("select count(*) from parent_chunks where material_id=%s", (material,)).fetchone()[0] == 1
        assert conn.execute("update parent_chunks set content='forged' where material_id=%s returning id", (material,)).fetchone() is None
        try:
            with conn.transaction(): conn.execute("select parent_context_blocks(%s,%s,%s)", (owner, subject, [blocks[2]["id"]]))
        except psycopg.errors.InsufficientPrivilege: pass
        else: raise AssertionError("Browser invoked service RPC")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert conn.execute("select count(*) from parent_chunk_blocks where material_id=%s", (material,)).fetchone()[0] == 0
        conn.execute("reset role")
        legacy = {"parents": [], "records": build_block_chunk_records(blocks[:1])}
        assert len(replace(legacy, "baseline")) == 1
        assert conn.execute("select count(*) from parent_chunks where material_id=%s", (material,)).fetchone()[0] == 0
        assert conn.execute("select count(*) from material_chunks where material_id=%s", (material,)).fetchone()[0] == 1
        print("PASS: read-only/cross-owner RLS, service-only RPC, baseline restoration and stale trailing chunk removal")
        conn.rollback(); print("All acceptance fixtures rolled back; existing indices unchanged.")
        if args.api:
            row = conn.execute("select b.id,b.user_id,b.subject_id from content_blocks b join materials m on m.id=b.material_id and m.user_id=b.user_id and m.subject_id=b.subject_id where m.status='ready' order by b.created_at limit 1").fetchone()
            if not row: raise SystemExit("No existing ready block for read-only API smoke")
            from fastapi import HTTPException
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.db.supabase_client import get_supabase_client
            from app.main import app
            from app.models.user import CurrentUser
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"; os.environ["no_proxy"] = os.environ["NO_PROXY"]
            db = get_supabase_client()
            result = db.rpc("parent_context_blocks", {"p_user_id": str(row[1]), "p_subject_id": str(row[2]), "p_block_ids": [str(row[0])]}).execute().data
            assert isinstance(result, list) and all(block["anchorBlockId"] == str(row[0]) for block in result)
            assert db.rpc("parent_context_blocks", {"p_user_id": str(foreign), "p_subject_id": str(row[2]), "p_block_ids": [str(row[0])]}).execute().data == []
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]))
            try:
                with patch("app.services.retrieval_service._get_subject_embedding_dimension", side_effect=HTTPException(404)), patch("app.services.retrieval_service._subject_has_lightrag_index", return_value=False), TestClient(app) as client:
                    for strategy in ["baseline", "adaptive"]:
                        response = client.post("/api/v1/retrieval/search", json={"subjectId": str(row[2]), "question": "definition", "strategy": strategy})
                        assert response.status_code == 200, response.text
                        assert response.json()["retrieval"]["pipelineVersion"] == "retrieval-v3-parent-child"
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(foreign))
                    assert client.post("/api/v1/retrieval/search", json={"subjectId": str(row[2]), "question": "definition"}).status_code == 404
                    print("PASS: real Supabase parent-context RPC, keyword API strategies and cross-owner 404; external model/vector/graph disabled")
            finally: app.dependency_overrides.pop(get_current_user, None)


if __name__ == "__main__": main()
