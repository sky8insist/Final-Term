"""Read-only local Supabase/API smoke. Auth is overridden, not a JWT E2E test."""
import os
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.api.deps import get_current_user
from app.config.settings import settings
from app.main import app
from app.models.user import CurrentUser
from app.services.recommendation_eval_service import audit_recommendations


def main():
    local = {"localhost", "127.0.0.1", "::1"}
    if (urlparse(settings.database_url or "").hostname not in local
            or urlparse(settings.supabase_url or "").hostname not in local):
        raise SystemExit("Refusing a non-local database or Supabase URL")
    columns = {
        "subjects": ("subjects", "id,name"),
        "topics": ("knowledge_points", "id,subject_id,knowledge_key,title,archived,importance"),
        "mastery": ("knowledge_mastery", "subject_id,knowledge_key,mastery,confidence,attempts,correct_attempts,last_reviewed_at,next_review_at,metadata"),
        "coverage": ("topic_coverage", "knowledge_point_id"),
        "events": ("exam_events", "id,subject_id,title,exam_date,status"),
        "mappings": ("exam_topic_map", "exam_event_id,knowledge_point_id,weight"),
        "tasks": ("review_tasks", "id,subject_id,title,estimated_minutes,scheduled_date,status"),
    }
    with psycopg.connect(settings.database_url, connect_timeout=5, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        subject = conn.execute("select id,user_id from subjects order by created_at,id limit 1").fetchone()
        if not subject:
            raise SystemExit("N/A: no local course; no live verification performed")
        subject_id, owner = str(subject["id"]), str(subject["user_id"])
        snapshot = {}
        for key, (table, fields) in columns.items():
            scope = "id" if table == "subjects" else "subject_id"
            rows = conn.execute(f"select {fields} from {table} where user_id=%s and {scope}=%s", (owner, subject_id)).fetchall()
            snapshot[key] = [{name: value.isoformat() if isinstance(value, (date, datetime)) else str(value)
                              if name in {"id", "subject_id", "exam_event_id", "knowledge_point_id"} else value
                              for name, value in row.items()} for row in rows]
    os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    previous_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides.pop(get_current_user, None)
        with TestClient(app) as client:
            assert client.get("/api/v1/recommendations/next-actions").status_code == 401
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=owner, email=None)
            response = client.get("/api/v1/recommendations/next-actions", params={"subject_id": subject_id})
            assert response.status_code == 200, f"recommendations HTTP {response.status_code}"
            result = response.json()
            audit = audit_recommendations(snapshot, result, now=datetime.fromisoformat(result["generatedAt"]))
            assert not audit["violations"], "Live recommendation failed snapshot audit (content omitted)"
            assert len(result["actions"]) <= 3
            print(f"PASS: actual Supabase API 200; actions={len(result['actions'])}, audited claims={len(audit['claims'])}")
            if not audit["claims"]:
                print("N/A: no live reason claims; offline claim checks still required")
            assert client.get("/api/v1/recommendations/next-actions", params={"limit": 0}).status_code == 422
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(uuid4()), email=None)
            assert client.get("/api/v1/recommendations/next-actions", params={"subject_id": subject_id}).status_code == 404
            print("PASS: unauthenticated 401, invalid limit 422, cross-owner subject 404; no database writes")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


if __name__ == "__main__":
    main()
