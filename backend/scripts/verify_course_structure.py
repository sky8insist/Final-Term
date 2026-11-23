"""Apply/verify P0 migrations locally; all acceptance rows are rolled back."""
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
    parser.add_argument("--apply", action="store_true", help="Apply absent P0 migrations; localhost only")
    parser.add_argument("--api", action="store_true", help="Read-only TestClient smoke with local Supabase; auth dependency override")
    args = parser.parse_args()
    url = settings.database_url or ""
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Refusing to touch a non-local database")
    with psycopg.connect(url, connect_timeout=5) as conn:
        migrations = [("029_course_structure.sql", "knowledge_points", "unit_id"),
                      ("030_topic_coverage.sql", "topic_coverage", "covered_at"),
                      ("031_response_confidence.sql", "exam_responses", "learner_confidence"),
                      ("032_exam_events_and_syllabi.sql", "exam_events", "exam_date")]
        for filename, table, column in migrations:
            exists = conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name=%s and column_name=%s)", (table, column)).fetchone()[0]
            if not exists:
                if not args.apply: raise SystemExit(f"{filename} missing; run with --apply")
                migration = (Path(__file__).resolve().parents[1] / "migrations" / filename).read_text(encoding="utf-8")
                conn.execute(migration)
                conn.commit()
                print(f"{filename} applied locally")
            else:
                print(f"{filename} already installed")

        # Every row below is ephemeral; no existing learner records are modified.
        conn.execute("select set_config('request.jwt.claims', '{\"role\":\"service_role\"}', true)")
        users = [uuid4(), uuid4()]
        subjects = [uuid4(), uuid4(), uuid4()]
        for user in users:
            conn.execute("insert into auth.users(id) values (%s)", (user,))
        for subject, user in zip(subjects, [users[0], users[0], users[1]]):
            conn.execute("insert into subjects(id,user_id,name) values (%s,%s,'course-verification')", (subject, user))
        topic = conn.execute("select (resolve_course_topic(%s,%s,' Matrix  Basics ')).id", (users[0], subjects[0])).fetchone()[0]
        same = conn.execute("select (resolve_course_topic(%s,%s,'matrix basics')).id", (users[0], subjects[0])).fetchone()[0]
        assert topic == same
        conn.execute("update knowledge_points set title='Renamed by user' where id=%s", (topic,))
        title = conn.execute("select (resolve_course_topic(%s,%s,'matrix basics')).title", (users[0], subjects[0])).fetchone()[0]
        assert title == "Renamed by user"
        other_subject = conn.execute("select (resolve_course_topic(%s,%s,'matrix basics')).id", (users[0], subjects[1])).fetchone()[0]
        other_owner = conn.execute("select (resolve_course_topic(%s,%s,'matrix basics')).id", (users[1], subjects[2])).fetchone()[0]
        assert len({topic, other_subject, other_owner}) == 3
        conn.execute("insert into topic_coverage values(%s,%s,%s,now()) on conflict do nothing", (users[0], subjects[0], topic))
        first_coverage = conn.execute("select covered_at from topic_coverage where knowledge_point_id=%s", (topic,)).fetchone()[0]
        conn.execute("insert into topic_coverage values(%s,%s,%s,now()) on conflict do nothing", (users[0], subjects[0], topic))
        assert conn.execute("select covered_at from topic_coverage where knowledge_point_id=%s", (topic,)).fetchone()[0] == first_coverage
        syllabus = conn.execute("select (create_course_syllabus(%s,%s,%s)).id", (users[0], subjects[0],
            psycopg.types.json.Jsonb({"title": "Acceptance syllabus", "content": {"source": "manual"}, "topic_ids": [str(topic)]}))).fetchone()[0]
        event_values = {"title": "Acceptance exam", "exam_date": "2026-10-10", "syllabus_id": str(syllabus),
                        "topics": [{"knowledge_point_id": str(topic), "weight": 5}]}
        event = conn.execute("select (save_course_exam(%s,%s,null,%s)).id", (users[0], subjects[0], psycopg.types.json.Jsonb(event_values))).fetchone()[0]
        assert conn.execute("select weight from exam_topic_map where exam_event_id=%s", (event,)).fetchone()[0] == 5
        invalid = {**event_values, "title": "Must roll back", "topics": [{"knowledge_point_id": str(other_subject), "weight": 1}]}
        try:
            with conn.transaction():
                conn.execute("select save_course_exam(%s,%s,%s,%s)", (users[0], subjects[0], event, psycopg.types.json.Jsonb(invalid)))
        except psycopg.errors.ForeignKeyViolation:
            pass
        else: raise AssertionError("Cross-subject exam scope accepted")
        assert conn.execute("select title from exam_events where id=%s", (event,)).fetchone()[0] == "Acceptance exam"
        assert conn.execute("select count(*) from exam_topic_map where exam_event_id=%s", (event,)).fetchone()[0] == 1
        # Confidence round-trip on an existing response is rolled back at the end.
        response = conn.execute("select id from exam_responses limit 1").fetchone()
        if response:
            conn.execute("update exam_responses set learner_confidence=0.9 where id=%s", response)
            assert conn.execute("select learner_confidence from exam_responses where id=%s", response).fetchone()[0] == 0.9
            try:
                with conn.transaction():
                    conn.execute("update exam_responses set learner_confidence=1.1 where id=%s", response)
            except psycopg.errors.CheckViolation:
                pass
            else: raise AssertionError("Out-of-range confidence accepted")
            print("PASS: response confidence round-trip and DB bounds")
        else:
            print("N/A: no existing response for confidence round-trip")
        unit = conn.execute("insert into knowledge_units(user_id,subject_id,title) values (%s,%s,'Unit') returning id", (users[0], subjects[1])).fetchone()[0]
        try:
            with conn.transaction():
                conn.execute("update knowledge_points set unit_id=%s where id=%s", (unit, topic))
        except psycopg.errors.ForeignKeyViolation:
            pass
        else:
            raise AssertionError("Cross-subject unit relation was accepted")
        conn.execute("select set_config('request.jwt.claims', %s, true)", ('{"role":"authenticated","sub":"' + str(users[1]) + '"}',))
        conn.execute("set local role authenticated")
        assert conn.execute("select count(*) from knowledge_points where id=%s", (topic,)).fetchone()[0] == 0
        assert conn.execute("select count(*) from topic_aliases where knowledge_point_id=%s", (topic,)).fetchone()[0] == 0
        for table in ["topic_coverage", "syllabi", "syllabus_topics", "exam_events", "exam_topic_map"]:
            assert conn.execute(f"select count(*) from {table} where user_id=%s", (users[0],)).fetchone()[0] == 0
        print("PASS: idempotent coverage, syllabus/exam linkage, atomic scope replacement, new-table authenticated RLS")
        print("PASS: alias identity, rename preservation, owner/subject isolation, composite FK, authenticated RLS")
        conn.rollback()
        print("Acceptance rows rolled back")
        if args.api:
            row = conn.execute("select id,user_id from subjects order by created_at limit 1").fetchone()
            if not row: raise SystemExit("No local subject for API smoke")
            from fastapi.testclient import TestClient
            from app.main import app
            from app.api.deps import get_current_user
            from app.models.user import CurrentUser
            subject_id, owner = map(str, row)
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
            os.environ["no_proxy"] = os.environ["NO_PROXY"]
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=owner, email=None)
            try:
                with TestClient(app) as test_client:
                    for suffix in ["structure", "learner-state", "exam-goals"]:
                        result = test_client.get(f"/api/v1/courses/{subject_id}/{suffix}")
                        if result.status_code != 200: raise AssertionError(f"{suffix}: HTTP {result.status_code}")
                        print(f"PASS: local API {suffix}, HTTP 200")
                    result = test_client.get("/api/v1/recommendations/next-actions", params={"subject_id": subject_id})
                    if result.status_code != 200: raise AssertionError(f"recommendations: HTTP {result.status_code}")
                    print(f"PASS: local API next-actions, HTTP 200, actions={len(result.json()['actions'])}")
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(uuid4()), email=None)
                    assert test_client.get(f"/api/v1/courses/{subject_id}/structure").status_code == 404
                    assert test_client.get("/api/v1/recommendations/next-actions", params={"subject_id": subject_id}).status_code == 404
                    print("PASS: local API cross-owner scope returns 404")
            finally:
                app.dependency_overrides.pop(get_current_user, None)


if __name__ == "__main__":
    main()
