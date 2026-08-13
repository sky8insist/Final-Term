"""Verify the local self-hosted Supabase instance without printing secrets."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.e2e_acceptance import check_schema, load_env_file


def main() -> int:
    env = load_env_file(ROOT.parent / ".env")
    required = [
        "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_JWT_SECRET", "DATABASE_URL",
    ]
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise RuntimeError(f"Missing configuration: {', '.join(missing)}")

    base_url = env["SUPABASE_URL"].rstrip("/")
    anon_key = env["SUPABASE_ANON_KEY"]
    service_key = env["SUPABASE_SERVICE_ROLE_KEY"]
    checks: dict[str, object] = {}

    schema = check_schema(env["DATABASE_URL"])
    checks["applicationSchema"] = schema.passed
    if not schema.passed:
        checks["applicationSchemaDetail"] = schema.detail

    with psycopg.connect(env["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select exists(select 1 from storage.buckets where id = 'study-materials')"
            )
            checks["studyMaterialsBucket"] = bool(cursor.fetchone()[0])
            cursor.execute(
                "select count(*) from information_schema.tables "
                "where table_schema = 'public' and table_type = 'BASE TABLE'"
            )
            checks["publicTableCount"] = int(cursor.fetchone()[0])

    created_user_id: str | None = None
    with httpx.Client(timeout=20.0) as client:
        anon_headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}
        auth_health = client.get(f"{base_url}/auth/v1/health", headers=anon_headers)
        checks["authHealth"] = auth_health.status_code == 200

        rest = client.get(
            f"{base_url}/rest/v1/materials?select=id&limit=1",
            headers=anon_headers,
        )
        checks["restApi"] = rest.status_code == 200

        buckets = client.get(
            f"{base_url}/storage/v1/bucket",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        )
        checks["storageApi"] = buckets.status_code == 200
        if buckets.status_code == 200:
            checks["storageBucketVisible"] = any(
                item.get("id") == "study-materials" for item in buckets.json()
            )

        email = f"local-supabase-check-{uuid4().hex}@example.com"
        try:
            signup = client.post(
                f"{base_url}/auth/v1/signup",
                headers={"apikey": anon_key, "Content-Type": "application/json"},
                json={"email": email, "password": f"Check-{uuid4().hex}!"},
            )
            checks["signup"] = signup.status_code == 200
            if signup.status_code == 200:
                body = signup.json()
                created_user_id = (body.get("user") or {}).get("id")
                token = body.get("access_token")
                payload = jwt.decode(
                    token,
                    env["SUPABASE_JWT_SECRET"],
                    algorithms=["HS256"],
                    audience="authenticated",
                )
                checks["backendJwtCompatibility"] = bool(payload.get("sub"))
        finally:
            if created_user_id:
                deleted = client.delete(
                    f"{base_url}/auth/v1/admin/users/{created_user_id}",
                    headers={
                        "apikey": service_key,
                        "Authorization": f"Bearer {service_key}",
                    },
                )
                checks["testUserRemoved"] = deleted.status_code in {200, 204}

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if all(value is True or isinstance(value, int) and value > 0 for value in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
