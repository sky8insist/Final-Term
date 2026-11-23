"""Local-only migration and rollback acceptance for card scheduling; no model calls."""
import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.config.settings import settings
from app.services.flashcard_service import schedule


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    url = settings.database_url or ""
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}: raise SystemExit("Refusing a non-local database")
    with psycopg.connect(url, connect_timeout=5, row_factory=dict_row) as conn:
        if not conn.execute("select to_regclass('public.flashcard_review_state') as installed").fetchone()["installed"]:
            if not args.apply: raise SystemExit("Missing 038_flashcard_scheduler.sql; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "038_flashcard_scheduler.sql").read_text(encoding="utf-8"))
            conn.commit(); print("Applied locally: 038_flashcard_scheduler.sql")
        conn.execute("notify pgrst, 'reload schema'"); conn.commit()
        conn.execute("select set_config('request.jwt.claims', '{\"role\":\"service_role\"}', true)")
        owner, foreign, subject, deck = [uuid4() for _ in range(4)]
        for user in [owner, foreign]: conn.execute("insert into auth.users(id) values(%s)", (user,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Card rollback acceptance')", (subject, owner))
        topic = conn.execute("select (resolve_course_topic(%s,%s,'Card Topic')).*", (owner, subject)).fetchone()
        content = {"cards": [{"id": key, "front": "Question", "back": "Answer", "knowledgePointId": str(topic["id"])} for key in ["A", "B"]]}
        conn.execute("insert into artifacts(id,user_id,subject_id,artifact_type,title,content) values(%s,%s,%s,'flashcards','Test deck',%s)", (deck, owner, subject, Jsonb(content)))
        def state(card): return conn.execute("select * from flashcard_review_state where artifact_id=%s and card_id=%s", (deck, card)).fetchone()
        def values(card, rating):
            current = conn.execute("select * from knowledge_mastery where user_id=%s and subject_id=%s and knowledge_key=%s", (owner, subject, topic["knowledge_key"])).fetchone()
            s = state(card); now = datetime.now(UTC)
            proposal = schedule({**s, "last_review": s["last_review"].isoformat() if s["last_review"] else None}, rating, now=now)
            return {**proposal, "topicId": str(topic["id"]), "masteryUpdatedAt": current["updated_at"].isoformat() if current else None,
                    "mastery": {"knowledge_key": topic["knowledge_key"], "mastery": 0.5, "confidence": 0,
                        "attempts": (current["attempts"] if current else 0) + 1, "correct_attempts": 0,
                        "last_reviewed_at": now.isoformat(), "next_review_at": proposal["nextReview"], "metadata": {}},
                    "evidence": {"evidenceType": "flashcard", "rating": rating}}
        def commit(card, rating, version, request, payload):
            return conn.execute("select commit_flashcard_review(%s,%s,%s,%s,%s,%s,%s) as result", (owner, deck, card, request, version, rating, Jsonb(payload))).fetchone()["result"]
        request = uuid4(); payload = values("A", "again")
        saved = commit("A", "again", 0, request, payload)
        assert state("A")["review_count"] == 1 and state("A")["lapse_count"] == 1 and state("B")["review_count"] == 0
        assert commit("A", "again", 0, request, payload) == saved
        assert conn.execute("select count(*) as n from learning_events where user_id=%s and event_type='flashcard_review'", (owner,)).fetchone()["n"] == 1
        assert conn.execute("select attempts from knowledge_mastery where user_id=%s", (owner,)).fetchone()["attempts"] == 1
        for card, rating, version, rid in [("A", "again", 0, uuid4()), ("B", "easy", 0, request)]:
            try:
                with conn.transaction(): commit(card, rating, version, rid, values(card, rating))
            except psycopg.errors.SerializationFailure: pass
            else: raise AssertionError("Stale version or reused request accepted")
        # A stale mastery snapshot must roll back the card update as well.
        stale = values("B", "easy"); stale["masteryUpdatedAt"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        try:
            with conn.transaction(): commit("B", "easy", 0, uuid4(), stale)
        except psycopg.errors.SerializationFailure: pass
        else: raise AssertionError("Stale mastery accepted")
        assert state("B")["version"] == 0
        commit("B", "easy", 0, uuid4(), values("B", "easy"))
        assert state("A")["next_review"] < state("B")["next_review"]
        print("PASS: independent card schedules, Again < Easy, atomic receipt replay and stale card/mastery rollback")
        content["cards"][0]["back"] = "Changed answer"
        conn.execute("update artifacts set content=%s where id=%s", (Jsonb(content), deck))
        assert state("A")["review_count"] == 0 and state("A")["content_version"] == 2 and state("B")["review_count"] == 1
        assert conn.execute("select count(*) as n from flashcard_review_logs where artifact_id=%s", (deck,)).fetchone()["n"] == 2
        queue = conn.execute("select flashcard_queue(%s,%s,null,false,50) as result", (owner, subject)).fetchone()["result"]
        assert queue["dueCount"] == 1 and queue["cards"][0]["card_id"] == "A" and not queue["hasMore"]
        conn.execute("update knowledge_points set archived=true where id=%s", (topic["id"],))
        assert conn.execute("select flashcard_queue(%s,%s,null,true,50) as result", (owner, subject)).fetchone()["result"]["totalCount"] == 0
        try:
            with conn.transaction(): commit("A", "good", state("A")["version"], uuid4(), values("A", "good"))
        except psycopg.errors.SerializationFailure: pass
        else: raise AssertionError("Archived topic accepted")
        conn.execute("update knowledge_points set archived=false where id=%s", (topic["id"],))
        content["cards"] = content["cards"][1:]
        conn.execute("update artifacts set content=%s where id=%s", (Jsonb(content), deck))
        assert conn.execute("select archived from flashcards where artifact_id=%s and card_id='A'", (deck,)).fetchone()["archived"]
        print("PASS: content-change reset, history preservation, due counts, removed/archived topic exclusion")
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        conn.execute("select set_config('request.jwt.claims',%s,true)", (f'{{"sub":"{owner}","role":"authenticated"}}',))
        for table in ["flashcards", "flashcard_review_state", "flashcard_review_logs"]:
            assert conn.execute(f"select count(*) as n from {table} where artifact_id=%s", (deck,)).fetchone()["n"] == 2
        assert conn.execute("update flashcard_review_state set review_count=999 where artifact_id=%s returning card_id", (deck,)).fetchone() is None
        try:
            with conn.transaction(): conn.execute("select flashcard_queue(%s,null,null,true,50)", (owner,))
        except psycopg.errors.InsufficientPrivilege: pass
        else: raise AssertionError("Browser invoked service-only RPC")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        conn.execute("select set_config('request.jwt.claims',%s,true)", (f'{{"sub":"{foreign}","role":"authenticated"}}',))
        for table in ["flashcards", "flashcard_review_state", "flashcard_review_logs"]:
            assert conn.execute(f"select count(*) as n from {table} where artifact_id=%s", (deck,)).fetchone()["n"] == 0
        print("PASS: owner read-only RLS, service-only RPC and cross-owner isolation")
        conn.rollback(); print("All acceptance fixture rows rolled back.")
        if args.api:
            row = conn.execute("select id,user_id from subjects order by created_at limit 1").fetchone()
            if not row: raise SystemExit("No local subject for read-only API smoke")
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"; os.environ["no_proxy"] = os.environ["NO_PROXY"]
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row["user_id"]))
            try:
                with TestClient(app) as client:
                    for params in [{}, {"subject_id": str(row["id"])}, {"subject_id": str(row["id"]), "include_future": True}]:
                        result = client.get("/api/v1/flashcards/queue", params=params)
                        assert result.status_code == 200, result.text
                        assert "dueCount" in result.json()
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(foreign))
                    assert client.get("/api/v1/flashcards/queue", params={"subject_id": str(row["id"])}).status_code == 404
                    print("PASS: real local Supabase queue/summary API and cross-owner 404 (auth dependency override)")
            finally: app.dependency_overrides.pop(get_current_user, None)


if __name__ == "__main__": main()
