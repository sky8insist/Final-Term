"""Local-only atomic plan migration acceptance. All fixture rows roll back."""
import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true"); parser.add_argument("--api", action="store_true"); args = parser.parse_args()
    url = settings.database_url or ""
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}: raise SystemExit("Local database required")
    with psycopg.connect(url, connect_timeout=5) as conn:
        installed = conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name='study_plans' and column_name='version')").fetchone()[0]
        if not installed:
            if not args.apply: raise SystemExit("Missing 036 migration; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "036_study_plan_v3.sql").read_text(encoding="utf-8")); conn.commit()
            print("Applied locally: 036_study_plan_v3.sql")
        conn.execute("notify pgrst, 'reload schema'"); conn.commit()
        conn.execute("select set_config('request.jwt.claims','{\"role\":\"service_role\"}',true)")
        owner, foreign, subject = [uuid4() for _ in range(3)]
        for user in [owner, foreign]: conn.execute("insert into auth.users(id) values(%s)", (user,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'plan-v3-rollback')", (subject, owner))
        topic = conn.execute("select (resolve_course_topic(%s,%s,'Plan Topic')).id", (owner, subject)).fetchone()[0]
        day = conn.execute("select (now() at time zone 'Asia/Shanghai')::date").fetchone()[0]
        values = {"title": "v3", "exam_date": (day + timedelta(days=7)).isoformat(), "daily_minutes": 60, "mode": "STANDARD",
                  "strategy": {"algorithmVersion": "exam-state-scheduler-v3", "autoReplan": True}}
        task = {"knowledge_key": "Plan Topic", "knowledge_point_id": str(topic), "task_type": "concept_rebuild", "title": "test",
                "scheduled_date": day.isoformat(), "estimated_minutes": 20, "priority": 0.9, "metadata": {}}
        plan = conn.execute("select (save_study_plan_v3(%s,%s,null,0,%s,%s,true)).id", (owner, subject, Jsonb(values), Jsonb([task]))).fetchone()[0]
        for label, status, source, locked in [("complete", "completed", "system", False), ("manual", "pending", "user", False), ("lock", "pending", "system", True)]:
            conn.execute("insert into review_tasks(user_id,subject_id,plan_id,knowledge_key,task_type,title,scheduled_date,estimated_minutes,priority,status,source,locked) values(%s,%s,%s,%s,'fixed',%s,%s,10,1,%s,%s,%s)", (owner, subject, plan, label, label, day, status, source, locked))
        revision = conn.execute("select version from study_plans where id=%s", (plan,)).fetchone()[0]
        changed = {**task, "scheduled_date": (day + timedelta(days=2)).isoformat()}
        new_revision = conn.execute("select (save_study_plan_v3(%s,%s,%s,%s,%s,%s,true)).version", (owner, subject, plan, revision, Jsonb(values), Jsonb([changed]))).fetchone()[0]
        assert new_revision == revision + 1
        assert conn.execute("select count(*) from review_tasks where plan_id=%s", (plan,)).fetchone()[0] == 4
        assert conn.execute("select scheduled_date from review_tasks where plan_id=%s and knowledge_key='Plan Topic'", (plan,)).fetchone()[0] == day + timedelta(days=2)
        try:
            with conn.transaction(): conn.execute("select save_study_plan_v3(%s,%s,%s,%s,%s,%s,true)", (owner, subject, plan, new_revision, Jsonb(values), Jsonb([{**changed, "estimated_minutes": -1}])))
        except psycopg.errors.CheckViolation: pass
        else: raise AssertionError("Invalid task accepted")
        assert conn.execute("select version from study_plans where id=%s", (plan,)).fetchone()[0] == new_revision
        assert conn.execute("select count(*) from review_tasks where plan_id=%s", (plan,)).fetchone()[0] == 4
        try:
            with conn.transaction(): conn.execute("select save_study_plan_v3(%s,%s,%s,%s,%s,%s,true)", (owner, subject, plan, revision, Jsonb(values), Jsonb([changed])))
        except psycopg.errors.SerializationFailure: pass
        else: raise AssertionError("Stale plan accepted")
        print("PASS: atomic replacement, completed/manual/locked preservation, rollback and version conflict")
        conn.execute("insert into topic_coverage(user_id,subject_id,knowledge_point_id) values(%s,%s,%s)", (owner, subject, topic))
        assert conn.execute("select replan_required from study_plans where id=%s", (plan,)).fetchone()[0]
        assert conn.execute("select exists(select 1 from study_plan_replan_candidates() where id=%s)", (plan,)).fetchone()[0]
        conn.execute("update review_tasks set scheduled_date=%s where plan_id=%s and knowledge_key='Plan Topic'", (day - timedelta(days=1), plan))
        conn.execute("update study_plans set replan_required=false where id=%s", (plan,))
        assert conn.execute("select exists(select 1 from study_plan_replan_candidates() where id=%s)", (plan,)).fetchone()[0]
        assert conn.execute("select count(*) from study_plan_events where plan_id=%s", (plan,)).fetchone()[0] >= 3
        print("PASS: learning changes, missed-task candidates and persisted replan reasons")
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claims',%s,true)", (f'{{"sub":"{owner}","role":"authenticated"}}',))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        assert conn.execute("select count(*) from study_plans where id=%s", (plan,)).fetchone()[0] == 1
        assert conn.execute("update review_tasks set locked=false where plan_id=%s returning id", (plan,)).fetchone() is None
        conn.execute("select set_config('request.jwt.claims',%s,true)", (f'{{"sub":"{foreign}","role":"authenticated"}}',))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        assert conn.execute("select count(*) from study_plan_events where plan_id=%s", (plan,)).fetchone()[0] == 0
        print("PASS: owner read, server-only task mutation and cross-owner event RLS")
        conn.rollback(); print("All fixture rows rolled back; existing learner data unchanged.")
        if args.api:
            row = conn.execute("select id,user_id from subjects order by created_at limit 1").fetchone()
            if not row: raise SystemExit("No existing local subject for read-only API smoke")
            from fastapi.testclient import TestClient
            from app.api.deps import get_current_user
            from app.main import app
            from app.models.user import CurrentUser
            subject_id, owner_id = map(str, row)
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
            os.environ["no_proxy"] = os.environ["NO_PROXY"]
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=owner_id)
            try:
                with TestClient(app) as client:
                    assert client.get("/api/v1/study-sessions", params={"subject_id": subject_id}).status_code == 200
                    assert client.get("/api/v1/study-plans/overview", params={"subject_id": subject_id}).status_code == 200
                    for mode in ["CRAM", "STANDARD", "COMPREHENSIVE"]:
                        result = client.post("/api/v1/study-plans/preview", json={"subjectId": subject_id,
                            "examDate": (day + timedelta(days=7)).isoformat(), "mode": mode, "dailyMinutes": 60,
                            "availableMinutes": {day.isoformat(): 0}})
                        assert result.status_code == 200, f"preview {mode}: HTTP {result.status_code}"
                        assert result.json()["dailyUsage"][day.isoformat()] == 0
                    print("PASS: real local Supabase API session list, plan overview and three mode previews")
                    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(foreign))
                    assert client.get("/api/v1/study-sessions", params={"subject_id": subject_id}).status_code == 404
                    assert client.post("/api/v1/study-plans/preview", json={"subjectId": subject_id, "examDate": (day + timedelta(days=7)).isoformat()}).status_code == 404
                    print("PASS: cross-owner session list and plan preview return 404")
            finally: app.dependency_overrides.pop(get_current_user, None)


if __name__ == "__main__": main()
