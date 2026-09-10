from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from uuid import uuid4
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
DEFAULT_WORKDIR = ROOT / "data" / "acceptance"

ACCEPTANCE_RUN_ID = ""
ACCEPTANCE_EVENTS: list[dict[str, Any]] = []
ACCEPTANCE_METRICS: dict[str, Any] = {}
ACCEPTANCE_CHECKS: list[Check] = []

LINEAR_SUBJECT_NAME = "线性代数期末复习"
DATABASE_SUBJECT_NAME = "数据库系统复习"

LINEAR_TXT = """LA-C1 行列式为 0 当且仅当矩阵的行向量或列向量线性相关，因此方阵不可逆。
LA-C2 矩阵的秩等于最大线性无关行或列的个数，也等于行最简形中非零行的数量。
LA-C3 n 阶矩阵可对角化的充分必要条件是存在 n 个线性无关特征向量。
LA-C4 相似矩阵具有相同的特征多项式、特征值、行列式、迹和秩。
"""

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
    "processing_tasks": {"id", "user_id", "stage", "progress"},
    "material_assets": {"id", "user_id", "object_path"},
    "content_blocks": {"id", "block_type", "structured_data", "source_hash"},
    "memory_entries": {"id", "target", "content"},
    "memory_snapshots": {"id", "session_id", "assistant_memory", "user_profile"},
    "artifacts": {"id", "artifact_type", "content", "version"},
    "exams": {"id", "blueprint_id", "status"},
    "wrong_answers": {"id", "question_id", "diagnosis"},
    "study_plans": {"id", "exam_date", "daily_minutes"},
    "review_tasks": {"id", "knowledge_key", "scheduled_date"},
    "model_call_logs": {"id", "request_id", "trace_id", "acceptance_run_id", "estimated_cost"},
    "operation_metrics": {"id", "request_id", "trace_id", "acceptance_run_id", "duration_ms"},
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


def generate_dataset(workdir: Path) -> dict[str, Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    paths = {
        "linear_txt": workdir / "linear_algebra_core.txt",
        "linear_docx": workdir / "linear_algebra_mistakes.docx",
        "database_txt": workdir / "database_core.txt",
    }
    paths["linear_txt"].write_text(LINEAR_TXT, encoding="utf-8")
    paths["database_txt"].write_text(DATABASE_TXT, encoding="utf-8")
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


def register_confirmed_account(client: httpx.Client, api_url: str, supabase_url: str,
                               anon_key: str, username: str, password: str) -> Session:
    response = client.post(
        f"{api_url.rstrip('/')}/api/v1/auth/account/register",
        json={"username": username, "password": password},
    )
    if response.status_code not in {201, 409}:
        response.raise_for_status()
    return login_or_register(
        client, supabase_url, anon_key, f"{username}@account.examai.local", password,
    )


def api_headers(session: Session) -> dict[str, str]:
    request_id = str(uuid4())
    return {
        "Authorization": f"Bearer {session.token}",
        "X-Request-ID": request_id,
        "X-Trace-ID": ACCEPTANCE_RUN_ID,
        "X-Acceptance-Run-ID": ACCEPTANCE_RUN_ID,
    }


def api_json(client: httpx.Client, method: str, url: str, session: Session, **kwargs: Any) -> Any:
    headers = api_headers(session)
    started_at = time.perf_counter()
    response = client.request(method, url, headers=headers, **kwargs)
    ACCEPTANCE_EVENTS.append({
        "acceptanceRunId": ACCEPTANCE_RUN_ID,
        "timestamp": datetime.now().astimezone().isoformat(),
        "method": method,
        "path": httpx.URL(url).path,
        "statusCode": response.status_code,
        "durationMs": round((time.perf_counter() - started_at) * 1000),
        "requestId": response.headers.get("X-Request-ID") or headers["X-Request-ID"],
        "traceId": response.headers.get("X-Trace-ID") or ACCEPTANCE_RUN_ID,
    })
    response.raise_for_status()
    if response.status_code == 204:
        return None
    return response.json()


def create_subject(client: httpx.Client, api_url: str, session: Session, name: str) -> dict:
    existing = api_json(
        client, "GET", f"{api_url.rstrip('/')}/api/v1/subjects", session,
    )
    matched = next((item for item in existing if item.get("name") == name), None)
    if matched:
        return matched
    return api_json(
        client,
        "POST",
        f"{api_url.rstrip('/')}/api/v1/subjects",
        session,
        json={"name": name, "description": "E2E acceptance fixture"},
    )


def upload_material(client: httpx.Client, api_url: str, session: Session, subject_id: str,
                    path: Path, content_type: str, timeout: float) -> dict:
    return queue_and_wait(client, api_url, session, subject_id, path, content_type, timeout)["material"]


def has_text(payload: Any, expected: str) -> bool:
    return expected in json.dumps(payload, ensure_ascii=False)


def queue_and_wait(client: httpx.Client, api_url: str, session: Session,
                   subject_id: str, path: Path, content_type: str, timeout: float) -> dict:
    with path.open("rb") as file_obj:
        headers = api_headers(session)
        started_at = time.perf_counter()
        response = client.post(
            f"{api_url.rstrip('/')}/api/v1/materials/uploads", headers=headers,
            data={"subject_id": subject_id}, files={"file": (path.name, file_obj, content_type)},
        )
    ACCEPTANCE_EVENTS.append({
        "acceptanceRunId": ACCEPTANCE_RUN_ID, "timestamp": datetime.now().astimezone().isoformat(),
        "method": "POST", "path": "/api/v1/materials/uploads",
        "statusCode": response.status_code, "durationMs": round((time.perf_counter() - started_at) * 1000),
        "requestId": response.headers.get("X-Request-ID") or headers["X-Request-ID"],
        "traceId": response.headers.get("X-Trace-ID") or ACCEPTANCE_RUN_ID,
    })
    response.raise_for_status()
    queued = response.json()
    if queued.get("deduplicated") and queued.get("material", {}).get("status") == "ready":
        return queued
    task = queued.get("task")
    if not task:
        raise RuntimeError("Async upload did not return a task")
    current = wait_for_task(client, api_url, session, task["id"], timeout)
    materials = api_json(
        client, "GET", f"{api_url.rstrip('/')}/api/v1/materials", session,
        params={"subject_id": subject_id},
    )
    material_id = queued.get("material", {}).get("id")
    refreshed = next((item for item in materials if item.get("id") == material_id), queued.get("material"))
    return {**queued, "material": refreshed, "task": current}


def wait_for_task(client: httpx.Client, api_url: str, session: Session,
                  task_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/tasks/{task_id}", session)
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            if current["status"] != "succeeded":
                raise RuntimeError(f"Async task ended as {current['status']}: {current.get('errorMessage')}")
            return current
        time.sleep(1)
    raise RuntimeError("Async task did not finish before timeout")


def run_acceptance(args: argparse.Namespace) -> list[Check]:
    global ACCEPTANCE_RUN_ID, ACCEPTANCE_METRICS, ACCEPTANCE_CHECKS
    ACCEPTANCE_RUN_ID = args.acceptance_run_id or f"acceptance-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
    env_file = load_env_file(ROOT.parent / ".env")
    api_url = args.api_base_url or env_value("ACCEPTANCE_API_BASE_URL", env_file, "http://localhost:8000")
    supabase_url = args.supabase_url or env_value("SUPABASE_URL", env_file)
    supabase_anon_key = args.supabase_anon_key or env_value("SUPABASE_ANON_KEY", env_file)
    database_url = args.database_url or env_value("DATABASE_URL", env_file)
    if not supabase_url or not supabase_anon_key or not database_url:
        raise RuntimeError("SUPABASE_URL, SUPABASE_ANON_KEY, and DATABASE_URL are required")

    required_switches = {
        "MOCK_EXTERNAL_APIS": "false",
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "ENABLE_MINERU": "true",
    }
    invalid_switches = {
        name: env_value(name, env_file, "") for name, expected in required_switches.items()
        if str(env_value(name, env_file, "")).strip().lower() != expected
    }
    if invalid_switches:
        raise RuntimeError(
            "Real acceptance requires MOCK_EXTERNAL_APIS=false, "
            "CELERY_TASK_ALWAYS_EAGER=false, and ENABLE_MINERU=true"
        )
    price_keys = (
        "MODEL_INPUT_COST_PER_MILLION",
        "MODEL_OUTPUT_COST_PER_MILLION",
        "EMBEDDING_COST_PER_MILLION",
    )
    if any(float(env_value(key, env_file, "0") or 0) <= 0 for key in price_keys):
        raise RuntimeError("Real acceptance requires positive chat and embedding model prices")

    real_pdf = Path(args.pdf_file or env_value("ACCEPTANCE_PDF_FILE", env_file, ""))
    if not real_pdf.is_file() or real_pdf.suffix.lower() != ".pdf":
        raise RuntimeError("Set --pdf-file or ACCEPTANCE_PDF_FILE to an existing real PDF")

    paths = generate_dataset(Path(args.workdir))
    paths["linear_pdf"] = real_pdf.resolve()
    checks: list[Check] = [
        Check("real mode", True, "Mock disabled, Celery async, MinerU enabled"),
        Check("dataset", True, f"Using real PDF {real_pdf.name}; auxiliary fixtures in {Path(args.workdir)}"),
    ]
    ACCEPTANCE_CHECKS = checks

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

        suffix = ACCEPTANCE_RUN_ID[-12:].replace("-", "")
        password = env_value("ACCEPTANCE_USER_PASSWORD", env_file) or f"Acceptance!{uuid4().hex}"
        configured_a = env_value("ACCEPTANCE_USER_A_EMAIL", env_file)
        configured_b = env_value("ACCEPTANCE_USER_B_EMAIL", env_file)
        if configured_a:
            session_a = login_or_register(
                client, supabase_url, supabase_anon_key, configured_a,
                env_value("ACCEPTANCE_USER_A_PASSWORD", env_file) or password,
            )
        else:
            session_a = register_confirmed_account(
                client, api_url, supabase_url, supabase_anon_key, f"acca{suffix}", password,
            )
        if configured_b:
            session_b = login_or_register(
                client, supabase_url, supabase_anon_key, configured_b,
                env_value("ACCEPTANCE_USER_B_PASSWORD", env_file) or password,
            )
        else:
            session_b = register_confirmed_account(
                client, api_url, supabase_url, supabase_anon_key, f"accb{suffix}", password,
            )
        checks.append(Check("auth", True, "Created or logged in student A and student B"))

        subject_a = create_subject(client, api_url, session_a, LINEAR_SUBJECT_NAME)
        subject_b = create_subject(client, api_url, session_b, DATABASE_SUBJECT_NAME)
        checks.append(Check("subjects", True, f"A={subject_a['id']} B={subject_b['id']}"))

        materials_a = [upload_material(
            client, api_url, session_a, subject_a["id"],
            paths["linear_pdf"], "application/pdf", args.timeout,
        )]
        material_b = upload_material(
            client, api_url, session_b, subject_b["id"], paths["database_txt"], "text/plain", args.timeout,
        )
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

        subjects_b = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/subjects", session_b)
        checks.append(
            Check(
                "user isolation subjects",
                subject_a["id"] not in {item["id"] for item in subjects_b},
                "Student B cannot see Student A subject",
            )
        )

        foreign_materials = client.get(
            f"{api_url.rstrip('/')}/api/v1/materials",
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
            f"{api_url.rstrip('/')}/api/v1/retrieval/search",
            session_a,
            json={"subjectId": subject_a["id"], "question": "How does Chandler define strategy?", "topK": 5},
        )
        checks.append(Check(
            "retrieval Chandler page",
            any(item.get("pageNumber") in {6, 33} for item in retrieval_a.get("citations", [])),
            "Search should retrieve Chandler's definition on page 6 or 33",
        ))

        progress_before = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/review/{subject_a['id']}/progress", session_a)
        history_before = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/chat/history/{subject_a['id']}", session_a)

        answer_diag = api_json(
            client,
            "POST",
            f"{api_url.rstrip('/')}/api/v1/chat/ask",
            session_a,
            json={"subjectId": subject_a["id"], "question": "What are Whittington's four perspectives on strategy?"},
        )
        diag_has_expected_citation = any(
            item.get("pageNumber") == 23 for item in answer_diag.get("citations", [])
        )
        checks.append(
            Check(
                "chat strategy citations",
                bool(answer_diag.get("answer")) and diag_has_expected_citation,
                "Answer should cite Whittington's four perspectives on page 23",
            )
        )

        answer_insufficient = api_json(
            client,
            "POST",
            f"{api_url.rstrip('/')}/api/v1/chat/ask",
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

        history_after = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/chat/history/{subject_a['id']}", session_a)
        progress_after = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/review/{subject_a['id']}/progress", session_a)
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
            f"{api_url.rstrip('/')}/api/v1/chat/ask",
            session_b,
            json={"subjectId": subject_b["id"], "question": "BCNF 是什么？"},
        )
        checks.append(Check("cross subject DB-C2", has_text(answer_bcnf, "DB-C2"), "Database subject should cite DB-C2"))

        foreign_history = client.get(f"{api_url.rstrip('/')}/api/v1/chat/history/{subject_a['id']}", headers=api_headers(session_b))
        checks.append(
            Check(
                "user isolation history",
                foreign_history.status_code == 404,
                f"Student B history query for A subject returned HTTP {foreign_history.status_code}",
            )
        )

        golden_path = Path(args.golden_questions)
        golden_cases = json.loads(golden_path.read_text(encoding="utf-8"))
        golden_hits = 0
        for case in golden_cases:
            result = api_json(
                client, "POST", f"{api_url.rstrip('/')}/api/v1/retrieval/search", session_a,
                json={"subjectId": subject_a["id"], "question": case["question"], "topK": 5},
            )
            pages = {int(item["pageNumber"]) for item in result.get("citations", []) if item.get("pageNumber") is not None}
            accepted_pages = {int(page) for page in case.get("acceptedPages", [case["expectedPage"]])}
            hit = bool(accepted_pages & pages)
            golden_hits += hit
            checks.append(Check(
                f"golden {case['id']}", hit,
                f"expected pages {sorted(accepted_pages)}; retrieved pages {sorted(pages)}",
            ))
        recall_at_5 = golden_hits / len(golden_cases) if golden_cases else 0.0
        checks.append(Check("golden Recall@5", recall_at_5 >= args.min_recall_at_5,
                            f"{golden_hits}/{len(golden_cases)} = {recall_at_5:.3f}"))

        if args.full:
            audio_path_value = env_value("ACCEPTANCE_AUDIO_FILE", env_file)
            if not audio_path_value or not Path(audio_path_value).exists():
                checks.append(Check("audio ingestion", True, "N/A: no acceptance audio file configured"))
            else:
                audio_path = Path(audio_path_value)
                audio_type = {".wav": "audio/wav", ".m4a": "audio/mp4"}.get(audio_path.suffix.lower(), "audio/mpeg")
                audio_result = queue_and_wait(client, api_url, session_a, subject_a["id"], audio_path, audio_type, args.timeout)
                blocks = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/materials/{audio_result['material']['id']}/blocks", session_a)
                checks.append(Check("audio ingestion", any(item["block_type"] == "audio" and item.get("start_time") is not None for item in blocks), "Timestamped audio blocks exist"))

            session_id = str(uuid4())
            beginner = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/assistant/messages", session_a,
                                json={"subjectId": subject_a["id"], "sessionId": session_id, "role": "beginner", "message": "用小白能懂的方式解释什么是战略"})
            socratic = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/assistant/messages", session_a,
                               json={"subjectId": subject_a["id"], "sessionId": session_id, "role": "socratic", "message": "训练我比较计划战略与涌现战略"})
            checks.append(Check("role switching", beginner["role"]["id"] == "beginner" and socratic["role"]["id"] == "socratic", "Context retained in one session"))

            snapshot = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/memory-snapshots", session_a,
                                json={"sessionId": session_id, "subjectId": subject_a["id"]})
            checks.append(Check("Hermes frozen snapshot", snapshot["session_id"] == session_id, "Snapshot created and reused by session"))

            mind_map = None
            flashcards = None
            try:
                mind_map = api_json(
                    client, "POST", f"{api_url.rstrip('/')}/api/v1/artifacts/mind-maps", session_a,
                    json={"subjectId": subject_a["id"], "mode": "question",
                          "query": "战略有哪些主要定义与形成学派？"},
                )
            except httpx.HTTPError as exc:
                checks.append(Check("mind map", False, f"Generation failed: {exc}"))
            try:
                flashcards = api_json(
                    client, "POST", f"{api_url.rstrip('/')}/api/v1/artifacts/flashcards", session_a,
                    json={"subjectId": subject_a["id"], "scope": "期末高频概念", "count": 5},
                )
            except httpx.HTTPError as exc:
                checks.append(Check("flashcards", False, f"Generation failed: {exc}"))
            checks.append(Check(
                "artifacts",
                bool(mind_map and mind_map.get("artifact_type") == "mind_map")
                and bool(flashcards and flashcards.get("artifact_type") == "flashcards"),
                "Mind map and flashcards generated",
            ))

            exam_task = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/exams/generations", session_a, json={
                "subjectId": subject_a["id"], "title": "E2E 模拟卷", "durationMinutes": 30,
                "difficulty": "medium", "scope": "战略定义与战略学派", "assessmentType": "practice",
                "knowledgePolicy": "course_only",
                "questionTypes": [{"questionType": "single_choice", "count": 2, "pointsEach": 5}],
            })
            exam_task = wait_for_task(client, api_url, session_a, exam_task["id"], args.timeout)
            exam = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/exams/{exam_task['metadata']['examId']}", session_a)
            attempt = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/exam-attempts", session_a, json={"examId": exam["id"]})
            for question in attempt["exam"]["questions"]:
                api_json(client, "PATCH", f"{api_url.rstrip('/')}/api/v1/exam-attempts/{attempt['id']}/responses", session_a,
                         json={"questionId": question["id"], "response": ""})
            grade = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/exam-attempts/{attempt['id']}/submit", session_a)
            checks.append(Check("exam and grading", len(grade["results"]) == 2 and grade["maxScore"] == 10, "Versioned exam submitted and graded"))
            exam_export = client.get(
                f"{api_url.rstrip('/')}/api/v1/exams/{exam['id']}/export",
                headers=api_headers(session_a), params={"format": "pdf", "includeAnswers": "true"},
            )
            checks.append(Check(
                "exam export", exam_export.status_code == 200 and exam_export.content.startswith(b"%PDF"),
                f"HTTP {exam_export.status_code}; bytes={len(exam_export.content)}",
            ))

            exam_date = (datetime.now().date() + timedelta(days=7)).isoformat()
            plan_task = api_json(client, "POST", f"{api_url.rstrip('/')}/api/v1/study-plans/generations", session_a,
                                 json={"subjectId": subject_a["id"], "examDate": exam_date, "dailyMinutes": 45})
            wait_for_task(client, api_url, session_a, plan_task["id"], args.timeout)
            plan = api_json(client, "GET", f"{api_url.rstrip('/')}/api/v1/study-plans/overview?subject_id={subject_a['id']}", session_a)
            checks.append(Check("adaptive plan", bool(plan["tasks"]), f"Generated {len(plan['tasks'])} spaced tasks"))

        ACCEPTANCE_METRICS = api_json(
            client, "GET", f"{api_url.rstrip('/')}/api/v1/operations/metrics", session_a,
            params={"acceptanceRunId": ACCEPTANCE_RUN_ID, "days": 1},
        )
        export_payload = api_json(
            client, "GET", f"{api_url.rstrip('/')}/api/v1/privacy/export", session_a,
        )
        checks.append(Check(
            "privacy export", bool(export_payload),
            f"Exported {len(export_payload)} top-level sections",
        ))
        if (not configured_a and not configured_b) or args.delete_configured_accounts:
            deleted_a = api_json(
                client, "DELETE", f"{api_url.rstrip('/')}/api/v1/privacy/account", session_a,
                params={"confirm": "DELETE"},
            )
            deleted_b = api_json(
                client, "DELETE", f"{api_url.rstrip('/')}/api/v1/privacy/account", session_b,
                params={"confirm": "DELETE"},
            )
            checks.append(Check(
                "privacy cleanup", bool(deleted_a) and bool(deleted_b),
                "Deleted both run-scoped Supabase accounts and learning data",
            ))
        else:
            checks.append(Check(
                "privacy cleanup", False,
                "N/A: preserved explicitly configured acceptance accounts",
            ))

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


def write_reports(checks: list[Check], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = ACCEPTANCE_RUN_ID or f"acceptance-{uuid4().hex[:8]}"
    jsonl_path = output_dir / f"{stem}.jsonl"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"
    with jsonl_path.open("w", encoding="utf-8") as stream:
        for event in ACCEPTANCE_EVENTS:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        for check in checks:
            stream.write(json.dumps({
                "acceptanceRunId": ACCEPTANCE_RUN_ID, "type": "check",
                "name": check.name, "passed": check.passed, "detail": check.detail,
            }, ensure_ascii=False) + "\n")
        stream.write(json.dumps({
            "acceptanceRunId": ACCEPTANCE_RUN_ID, "type": "metrics",
            "metrics": ACCEPTANCE_METRICS,
        }, ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "acceptanceRunId", "timestamp", "method", "path", "statusCode",
            "durationMs", "requestId", "traceId",
        ])
        writer.writeheader()
        writer.writerows(ACCEPTANCE_EVENTS)
    passed = sum(check.passed for check in checks)
    model_metrics = ACCEPTANCE_METRICS.get("models") or {}
    lines = [
        f"# 真实 E2E 验收报告：{ACCEPTANCE_RUN_ID}", "",
        f"- 结果：{passed}/{len(checks)} 通过",
        f"- HTTP 调用：{len(ACCEPTANCE_EVENTS)}",
        f"- 模型调用：{model_metrics.get('calls', 'N/A')}",
        f"- 估算成本：{model_metrics.get('estimatedCost', 'N/A')} {model_metrics.get('currency', '')}".rstrip(),
        "", "## 检查结果", "",
        "| 状态 | 检查 | 详情 |", "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {'PASS' if check.passed else 'FAIL'} | {check.name.replace('|', '/')} | {check.detail.replace('|', '/')} |"
        for check in checks
    )
    lines.extend(["", "## 阶段与成本指标", "", "```json",
                  json.dumps(ACCEPTANCE_METRICS, ensure_ascii=False, indent=2), "```", ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"jsonl": str(jsonl_path), "csv": str(csv_path), "markdown": str(markdown_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Exam AI MVP end-to-end acceptance checks.")
    parser.add_argument("--api-base-url", default=None, help="Backend API URL. Default: ACCEPTANCE_API_BASE_URL or http://localhost:8000")
    parser.add_argument("--supabase-url", default=None, help="Supabase API URL. Default: SUPABASE_URL from project .env")
    parser.add_argument("--supabase-anon-key", default=None, help="Supabase anon key. Default: SUPABASE_ANON_KEY from project .env")
    parser.add_argument("--database-url", default=None, help="Postgres URL. Default: DATABASE_URL from project .env")
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR), help="Where generated fixture files are written")
    parser.add_argument("--pdf-file", default=None, help="Existing real PDF used for MinerU/indexing acceptance")
    parser.add_argument(
        "--golden-questions",
        default=str(ROOT.parent / "docs" / "acceptance" / "golden_questions.json"),
        help="Page-labeled Golden Questions JSON",
    )
    parser.add_argument("--min-recall-at-5", type=float, default=0.8)
    parser.add_argument("--acceptance-run-id", default=None)
    parser.add_argument(
        "--delete-configured-accounts", action="store_true",
        help="Delete explicitly configured acceptance accounts after export",
    )
    parser.add_argument(
        "--report-dir", default=str(ROOT / "data" / "acceptance" / "reports"),
        help="JSONL, CSV, and Markdown report directory",
    )
    parser.add_argument("--apply-migrations", action="store_true", help="Apply backend/migrations/*.sql before running checks")
    parser.add_argument("--generate-only", action="store_true", help="Only generate fixture files")
    parser.add_argument("--continue-on-failure", action="store_true", help="Keep running independent checks after a failure")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout in seconds")
    parser.add_argument("--full", action="store_true", help="Run multimodal, memory, role, artifact, exam, grading, and plan checks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.generate_only:
        paths = generate_dataset(Path(args.workdir))
        print(json.dumps({key: str(path) for key, path in paths.items()}, ensure_ascii=False, indent=2))
        return 0

    checks: list[Check]
    try:
        checks = run_acceptance(args)
    except Exception as exc:
        print(f"[FAIL] acceptance runner: {exc}", file=sys.stderr)
        checks = [*ACCEPTANCE_CHECKS, Check("acceptance runner", False, str(exc))]
    reports = write_reports(checks, Path(args.report_dir))
    print(json.dumps({"acceptanceRunId": ACCEPTANCE_RUN_ID, "reports": reports}, ensure_ascii=False, indent=2))
    return print_checks(checks)


if __name__ == "__main__":
    raise SystemExit(main())
