"""Local rollback acceptance for keyword scope, plus read-only keyword API smoke."""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from app.config.settings import settings


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true"); parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    url = settings.database_url or ""
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}: raise SystemExit("Refusing a non-local database")
    with psycopg.connect(url, connect_timeout=5) as conn:
        installed = conn.execute("select position('m.user_id=cb.user_id' in prosrc)>0 from pg_proc where oid='public.search_content_blocks(text,uuid,uuid,uuid[],text[],double precision,integer)'::regprocedure").fetchone()[0]
        if not installed:
            if not args.apply: raise SystemExit("Missing 039_retrieval_scope.sql; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "039_retrieval_scope.sql").read_text(encoding="utf-8")); conn.commit()
            print("Applied locally: 039_retrieval_scope.sql")
        conn.execute("notify pgrst, 'reload schema'"); conn.commit()
        owner, foreign, subject, other_subject, foreign_subject = [uuid4() for _ in range(5)]
        for uid in [owner, foreign]: conn.execute("insert into auth.users(id) values(%s)", (uid,))
        for sid, uid in [(subject, owner), (other_subject, owner), (foreign_subject, foreign)]:
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Retrieval rollback')", (sid, uid))
        blocks = []; materials = []
        def block(uid, sid, material=None):
            if material is None:
                material = conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,'fixture.txt','text/plain',1,'ready') returning id", (uid, sid)).fetchone()[0]
                materials.append(material)
            bid = conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,sequence_index,parser_name,parser_version,source_hash) values(%s,%s,%s,'paragraph','matrix isolation fixture',0,'acceptance','1',%s) returning id", (uid, sid, material, str(uuid4()))).fetchone()[0]
            blocks.append(bid); return bid
        expected = block(owner, subject); block(owner, other_subject); block(foreign, foreign_subject)
        # Legacy foreign keys allow a forged owned block pointing at a foreign material.
        # Joined material ownership must still prevent its filename/text being returned.
        block(owner, subject, materials[-1])
        def query(uid, sid, material_filter=None):
            return conn.execute("select id from search_content_blocks('matrix',%s,%s,%s,null,null,160)", (uid, sid, material_filter)).fetchall()
        assert query(owner, subject) == [(expected,)]
        assert query(owner, subject, [materials[1]]) == []
        assert query(foreign, subject) == [] and query(owner, foreign_subject) == []
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert query(owner, subject) == []
        print("PASS: real keyword owner/subject/material scope, forged cross-owner material exclusion and authenticated isolation")
        conn.rollback(); print("All acceptance fixture rows rolled back.")
        if args.api:
            row = conn.execute("select id,user_id from subjects order by created_at limit 1").fetchone()
            if not row: raise SystemExit("No local subject for API smoke")
            from fastapi import HTTPException
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"; os.environ["no_proxy"] = os.environ["NO_PROXY"]
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]))
            try:
                with patch("app.services.retrieval_service._get_subject_embedding_dimension", side_effect=HTTPException(404)), patch("app.services.retrieval_service._subject_has_lightrag_index", return_value=False), TestClient(app) as client:
                    for strategy in ["baseline", "adaptive"]:
                        result = client.post("/api/v1/retrieval/search", json={"subjectId": str(row[0]), "question": "What is matrix?", "strategy": strategy})
                        assert result.status_code == 200, result.text
                        assert result.json()["retrieval"]["topK"] == (5 if strategy == "baseline" else 3)
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(foreign))
                    assert client.post("/api/v1/retrieval/search", json={"subjectId": str(row[0]), "question": "matrix"}).status_code == 404
                    print("PASS: real Supabase keyword API baseline/adaptive and foreign subject 404; model/vector/graph paths disabled")
            finally: app.dependency_overrides.pop(get_current_user, None)


if __name__ == "__main__": main()
