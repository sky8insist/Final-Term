from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
DEFAULT_WORKDIR = ROOT / "data" / "acceptance"

STUDENT_A = ("student_a@example.com", "Test123456!")
STUDENT_B = ("student_b@example.com", "Test123456!")

LINEAR_SUBJECT_NAME = "线性代数期末复习"
DATABASE_SUBJECT_NAME = "数据库系统复习"

LINEAR_TXT = """LA-C1 行列式为 0 当且仅当矩阵的行向量或列向量线性相关，因此方阵不可逆。
LA-C2 矩阵的秩等于最大线性无关行或列的个数，也等于行最简形中非零行的数量。
LA-C3 n 阶矩阵可对角化的充分必要条件是存在 n 个线性无关特征向量。
LA-C4 相似矩阵具有相同的特征多项式、特征值、行列式、迹和秩。
"""

LINEAR_PDF_LINES = [
    "LA-P1 homogeneous system Ax=0 has non-zero solutions when rank(A)<n.",
    "LA-P2 non-homogeneous system Ax=b is solvable iff rank(A)=rank(A|b).",
    "LA-P3 orthogonal matrix Q satisfies Q^TQ=I and preserves length and inner product.",
]

LINEAR_DOCX = """LA-D1 常见错误：把“有 n 个特征值”误认为一定可对角化；正确条件是有 n 个线性无关特征向量。
LA-D2 常见错误：只看行列式判断非方阵可逆；可逆概念只适用于方阵。
LA-D3 复习优先级：先掌握秩、线性相关、方程组解，再复习特征值和对角化。
"""

DATABASE_TXT = """DB-C1 事务 ACID 包括原子性、一致性、隔离性和持久性。
DB-C2 BCNF 要求每一个非平凡函数依赖 X->Y 中，X 都必须是超码。
DB-C3 B+ 树适合范围查询，因为所有叶子节点按键值有序连接。
"""

REQUIRED_SCHEMA = {
    "subjects": {"id", "user_id", "name"},
    "materials": {"id", "user_id", "subject_id", "status"},
    "material_chunks": {"id", "user_id", "subject_id", "material_id", "content", "embedding"},
    "lightrag_material_index": {"id", "user_id", "subject_id", "material_id", "status"},
    "chat_messages": {"id", "user_id", "subject_id", "role", "content", "citations"},
    "review_progress": {"id", "user_id", "subject_id", "mastered_count", "total_count"},
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Session:
    email: str
    token: str
    user_id: str


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str, env_file: dict[str, str], default: str | None = None) -> str | None:
    return os.environ.get(name) or env_file.get(name) or default


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_pdf(path: Path, lines: list[str]) -> None:
    content_lines = ["BT", "/F1 11 Tf", "72 760 Td", "14 TL"]
    for index, line in enumerate(lines):
        if index:
            content_lines.append("T*")
        content_lines.append(f"({pdf_escape(line)}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(data)


def generate_dataset(workdir: Path) -> dict[str, Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    paths = {
        "linear_txt": workdir / "linear_algebra_core.txt",
        "linear_pdf": workdir / "linear_algebra_cases.pdf",
        "linear_docx": workdir / "linear_algebra_mistakes.docx",
        "database_txt": workdir / "database_core.txt",
    }
    paths["linear_txt"].write_text(LINEAR_TXT, encoding="utf-8")
    paths["database_txt"].write_text(DATABASE_TXT, encoding="utf-8")
    write_simple_pdf(paths["linear_pdf"], LINEAR_PDF_LINES)

    document = Document()
    for line in LINEAR_DOCX.strip().splitlines():
        document.add_paragraph(line)
    document.save(paths["linear_docx"])
    return paths


def apply_migrations(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                cursor.execute(migration.read_text(encoding="utf-8"))
        connection.commit()


def check_schema(database_url: str) -> Check:
    missing: list[str] = []
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for table, required_columns in REQUIRED_SCHEMA.items():
                cursor.execute(
                    """
                    select column_name
                    from information_schema.columns
                    where table_schema = 'public' and table_name = %s
                    """,
                    (table,),
                )
                columns = {row[0] for row in cursor.fetchall()}
                if not columns:
                    missing.append(f"{table} table")
                    continue
                for column in sorted(required_columns - columns):
                    missing.append(f"{table}.{column}")

            cursor.execute("select 1 from pg_extension where extname = 'vector'")
            if cursor.fetchone() is None:
                missing.append("pgvector extension")

    if missing:
        return Check("schema", False, "Missing: " + ", ".join(missing))
    return Check("schema", True, "Required MVP tables and pgvector are present")


def auth_headers(anon_key: str) -> dict[str, str]:
    return {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}


def login_or_register(client: httpx.Client, supabase_url: str, anon_key: str, email: str, password: str) -> Session:
    headers = auth_headers(anon_key)
    client.post(
        f"{supabase_url.rstrip('/')}/auth/v1/signup",
        headers=headers,
        json={"email": email, "password": password, "data": {"name": email.split("@")[0]}},
    )
    response = client.post(
        f"{supabase_url.rstrip('/')}/auth/v1/token?grant_type=password",
        headers=headers,
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    payload = response.json()
    return Session(
        email=email,
        token=payload["access_token"],
        user_id=payload["user"]["id"],
    )


def api_headers(session: Session) -> dict[str, str]:
    return {"Authorization": f"Bearer {session.token}"}


def api_json(client: httpx.Client, method: str, url: str, session: Session, **kwargs: Any) -> Any:
    response = client.request(method, url, headers=api_headers(session), **kwargs)
    response.raise_for_status()
    if response.status_code == 204:
        return None
    return response.json()


def create_subject(client: httpx.Client, api_url: str, session: Session, name: str) -> dict:
    return api_json(
        client,
        "POST",
        f"{api_url.rstrip('/')}/subjects",
        session,
        json={"name": name, "description": "E2E acceptance fixture"},
    )


def upload_material(client: httpx.Client, api_url: str, session: Session, subject_id: str, path: Path, content_type: str) -> dict:
    with path.open("rb") as file_obj:
        response = client.post(
            f"{api_url.rstrip('/')}/materials/upload",
            headers=api_headers(session),
            data={"subject_id": subject_id},
            files={"file": (path.name, file_obj, content_type)},
        )
    response.raise_for_status()
    return response.json()["material"]


def has_text(payload: Any, expected: str) -> bool:
    return expected in json.dumps(payload, ensure_ascii=False)


def run_acceptance(args: argparse.Namespace) -> list[Check]:
    env_file = load_env_file(ROOT / ".env")
    api_url = args.api_base_url or env_value("ACCEPTANCE_API_BASE_URL", env_file, "http://localhost:8000")
    supabase_url = args.supabase_url or env_value("SUPABASE_URL", env_file)
    supabase_anon_key = args.supabase_anon_key or env_value("SUPABASE_ANON_KEY", env_file)
    database_url = args.database_url or env_value("DATABASE_URL", env_file)
    if not supabase_url or not supabase_anon_key or not database_url:
        raise RuntimeError("SUPABASE_URL, SUPABASE_ANON_KEY, and DATABASE_URL are required")

    paths = generate_dataset(Path(args.workdir))
    checks: list[Check] = [Check("dataset", True, f"Generated fixtures in {Path(args.workdir)}")]

    if args.apply_migrations:
        apply_migrations(database_url)
        checks.append(Check("migrations", True, "Applied backend/migrations/*.sql"))

    checks.append(check_schema(database_url))
    if not checks[-1].passed and not args.continue_on_failure:
        return checks

    with httpx.Client(timeout=args.timeout) as client:
        health = client.get(f"{api_url.rstrip('/')}/health")
        checks.append(Check("backend health", health.status_code == 200, f"HTTP {health.status_code}"))
        if health.status_code != 200 and not args.continue_on_failure:
            return checks

        session_a = login_or_register(client, supabase_url, supabase_anon_key, *STUDENT_A)
        session_b = login_or_register(client, supabase_url, supabase_anon_key, *STUDENT_B)
        checks.append(Check("auth", True, "Created or logged in student A and student B"))

        subject_a = create_subject(client, api_url, session_a, LINEAR_SUBJECT_NAME)
        subject_b = create_subject(client, api_url, session_b, DATABASE_SUBJECT_NAME)
        checks.append(Check("subjects", True, f"A={subject_a['id']} B={subject_b['id']}"))

        materials_a = [
            upload_material(client, api_url, session_a, subject_a["id"], paths["linear_txt"], "text/plain"),
            upload_material(client, api_url, session_a, subject_a["id"], paths["linear_pdf"], "application/pdf"),
            upload_material(
                client,
                api_url,
                session_a,
                subject_a["id"],
                paths["linear_docx"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ]
        material_b = upload_material(client, api_url, session_b, subject_b["id"], paths["database_txt"], "text/plain")
        failed_materials = [item for item in [*materials_a, material_b] if item["status"] != "ready"]
        checks.append(
            Check(
                "upload processing",
                not failed_materials,
                "All materials ready" if not failed_materials else json.dumps(failed_materials, ensure_ascii=False),
            )
        )
        if failed_materials and not args.continue_on_failure:
            return checks

        subjects_b = api_json(client, "GET", f"{api_url.rstrip('/')}/subjects", session_b)
        checks.append(
            Check(
                "user isolation subjects",
                subject_a["id"] not in {item["id"] for item in subjects_b},
                "Student B cannot see Student A subject",
            )
        )

        foreign_materials = client.get(
            f"{api_url.rstrip('/')}/materials",
            headers=api_headers(session_b),
            params={"subject_id": subject_a["id"]},
        )
        checks.append(
            Check(
                "user isolation materials",
                foreign_materials.status_code == 404,
                f"Student B material query for A subject returned HTTP {foreign_materials.status_code}",
            )
        )

        retrieval_a = api_json(
            client,
            "POST",
            f"{api_url.rstrip('/')}/retrieval/search",
            session_a,
            json={"subjectId": subject_a["id"], "question": "矩阵什么时候不可逆？", "topK": 5},
        )
        checks.append(Check("retrieval LA-C1", has_text(retrieval_a, "LA-C1"), "Search should retrieve determinant criterion"))

        progress_before = api_json(client, "GET", f"{api_url.rstrip('/')}/review/{subject_a['id']}/progress", session_a)
        history_before = api_json(client, "GET", f"{api_url.rstrip('/')}/chat/history/{subject_a['id']}", session_a)

        answer_diag = api_json(
            client,
            "POST",
            f"{api_url.rstrip('/')}/chat/ask",
            session_a,
            json={"subjectId": subject_a["id"], "question": "矩阵可对角化的条件是什么？"},
        )
        diag_has_expected_citation = has_text(answer_diag.get("citations", []), "LA-C3") or has_text(
            answer_diag.get("citations", []), "LA-D1"
        )
        checks.append(
            Check(
                "chat diagonalization citations",
                bool(answer_diag.get("answer")) and diag_has_expected_citation,
                "Answer should cite LA-C3 or LA-D1",
            )
        )

        answer_insufficient = api_json(
            client,
            "POST",
            f"{api_url.rstrip('/')}/chat/ask",
            session_a,
            json={"subjectId": subject_a["id"], "question": "BCNF 是什么？"},
        )
        checks.append(
            Check(
                "insufficient context",
                "DB-C" not in json.dumps(answer_insufficient, ensure_ascii=False),
                "Linear algebra subject must not cite database material",
            )
        )

        history_after = api_json(client, "GET", f"{api_url.rstrip('/')}/chat/history/{subject_a['id']}", session_a)
        progress_after = api_json(client, "GET", f"{api_url.rstrip('/')}/review/{subject_a['id']}/progress", session_a)
        checks.append(
            Check(
                "history",
                len(history_after) >= len(history_before) + 4,
                f"History before={len(history_before)} after={len(history_after)}",
            )
        )
        checks.append(
            Check(
                "review progress",
                progress_after["totalCount"] >= progress_before["totalCount"] + 2,
                f"Progress before={progress_before['totalCount']} after={progress_after['totalCount']}",
            )
        )

        answer_bcnf = api_json(
            client,
            "POST",
            f"{api_url.rstrip('/')}/chat/ask",
            session_b,
            json={"subjectId": subject_b["id"], "question": "BCNF 是什么？"},
        )
        checks.append(Check("cross subject DB-C2", has_text(answer_bcnf, "DB-C2"), "Database subject should cite DB-C2"))

        foreign_history = client.get(f"{api_url.rstrip('/')}/chat/history/{subject_a['id']}", headers=api_headers(session_b))
        checks.append(
            Check(
                "user isolation history",
                foreign_history.status_code == 404,
                f"Student B history query for A subject returned HTTP {foreign_history.status_code}",
            )
        )

    return checks


def print_checks(checks: list[Check]) -> int:
    passed_count = 0
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        if check.passed:
            passed_count += 1
        print(f"[{status}] {check.name}: {check.detail}")
    print(json.dumps({"passed": passed_count, "total": len(checks)}, ensure_ascii=False, indent=2))
    return 0 if passed_count == len(checks) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Exam AI MVP end-to-end acceptance checks.")
    parser.add_argument("--api-base-url", default=None, help="Backend API URL. Default: ACCEPTANCE_API_BASE_URL or http://localhost:8000")
    parser.add_argument("--supabase-url", default=None, help="Supabase API URL. Default: SUPABASE_URL from backend/.env")
    parser.add_argument("--supabase-anon-key", default=None, help="Supabase anon key. Default: SUPABASE_ANON_KEY from backend/.env")
    parser.add_argument("--database-url", default=None, help="Postgres URL. Default: DATABASE_URL from backend/.env")
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR), help="Where generated fixture files are written")
    parser.add_argument("--apply-migrations", action="store_true", help="Apply backend/migrations/*.sql before running checks")
    parser.add_argument("--generate-only", action="store_true", help="Only generate fixture files")
    parser.add_argument("--continue-on-failure", action="store_true", help="Keep running independent checks after a failure")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.generate_only:
        paths = generate_dataset(Path(args.workdir))
        print(json.dumps({key: str(path) for key, path in paths.items()}, ensure_ascii=False, indent=2))
        return 0

    try:
        checks = run_acceptance(args)
    except Exception as exc:
        print(f"[FAIL] acceptance runner: {exc}", file=sys.stderr)
        return 1
    return print_checks(checks)


if __name__ == "__main__":
    raise SystemExit(main())
