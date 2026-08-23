from __future__ import annotations

import json
import httpx
import psycopg

from e2e_acceptance import (
    ROOT,
    STUDENT_A,
    api_json,
    env_value,
    load_env_file,
    login_or_register,
)


API_ROOT = "http://localhost:8000/api/v1"


def create_exam_fixture(*, database_url: str, user_id: str, subject_id: str) -> None:
    specification = {
        "questionTypes": [{"questionType": "single_choice", "count": 1, "pointsEach": 2}],
        "assessmentType": "practice", "scope": "逐题确认验收",
        "knowledgePolicy": "course_only", "retrieval": {"courseEvidenceCount": 1},
    }
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """insert into public.exam_blueprints
               (user_id, subject_id, title, duration_minutes, total_points, specification)
               values (%s, %s, %s, 10, 2, %s::jsonb) returning id""",
            (user_id, subject_id, "逐题确认验收练习", json.dumps(specification, ensure_ascii=False)),
        )
        blueprint_id = cursor.fetchone()[0]
        cursor.execute(
            """insert into public.exams
               (user_id, subject_id, blueprint_id, title, duration_minutes, total_points)
               values (%s, %s, %s, %s, 10, 2) returning id""",
            (user_id, subject_id, blueprint_id, "逐题确认验收练习"),
        )
        exam_id = cursor.fetchone()[0]
        cursor.execute(
            """insert into public.exam_sections
               (exam_id, title, instructions, sequence_index, points)
               values (%s, %s, %s, 0, 2) returning id""",
            (exam_id, "验收题", "选择答案后确认",),
        )
        section_id = cursor.fetchone()[0]
        cursor.execute(
            """insert into public.questions
               (user_id, subject_id, question_type, knowledge_key, difficulty, source_kind)
               values (%s, %s, 'single_choice', %s, 'easy', 'material') returning id""",
            (user_id, subject_id, "战略定义"),
        )
        question_id = cursor.fetchone()[0]
        cursor.execute(
            """insert into public.question_versions
               (question_id, version, stem, options, correct_answer, explanation, citations)
               values (%s, 1, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)""",
            (
                question_id, "战略首先关注哪一项？",
                json.dumps(["长期方向", "日常排班"], ensure_ascii=False),
                json.dumps("长期方向", ensure_ascii=False),
                "课程资料将战略界定为面向长期目标、行动方案与资源配置的整体方向。",
                json.dumps(["acceptance:course"]),
            ),
        )
        cursor.execute(
            """insert into public.exam_questions
               (exam_id, section_id, question_id, question_version, sequence_index, points)
               values (%s, %s, %s, 1, 0, 2)""",
            (exam_id, section_id, question_id),
        )
        connection.commit()


def sample_response(question: dict):
    question_type = question["question_type"]
    options = question.get("options") or []
    if question_type == "single_choice":
        return options[0]
    if question_type == "multiple_choice":
        return options[:1]
    if question_type == "true_false":
        return True
    return "端到端验收回答"


def changed_response(question: dict, original):
    options = question.get("options") or []
    if question["question_type"] == "single_choice" and len(options) > 1:
        return options[1]
    if question["question_type"] == "multiple_choice" and len(options) > 1:
        return options[-1:]
    if question["question_type"] == "true_false":
        return not original
    return f"{original}（修改）"


def main() -> int:
    env_file = load_env_file(ROOT.parent / ".env")
    supabase_url = env_value("SUPABASE_URL", env_file)
    anon_key = env_value("SUPABASE_ANON_KEY", env_file)
    database_url = env_value("DATABASE_URL", env_file)
    if not supabase_url or not anon_key or not database_url:
        raise RuntimeError("Local Supabase configuration is unavailable")

    with httpx.Client(timeout=120) as client:
        session = login_or_register(client, supabase_url, anon_key, *STUDENT_A)
        subjects = api_json(client, "GET", f"{API_ROOT}/subjects", session)
        exams = []
        for subject in subjects:
            exams.extend(api_json(
                client, "GET", f"{API_ROOT}/exams",
                session, params={"subject_id": subject["id"]},
            ))
        if not exams:
            if subjects:
                subject = subjects[0]
            else:
                subject = api_json(
                    client, "POST", f"{API_ROOT}/subjects", session,
                    json={"name": "逐题确认验收", "description": "本地验收夹具"},
                )
            create_exam_fixture(
                database_url=database_url, user_id=session.user_id, subject_id=subject["id"],
            )
            exams = api_json(
                client, "GET", f"{API_ROOT}/exams", session,
                params={"subject_id": subject["id"]},
            )

        attempt = None
        for exam in exams:
            candidate = api_json(
                client, "POST", f"{API_ROOT}/exam-attempts",
                session, json={"examId": exam["id"]},
            )
            if candidate.get("exam", {}).get("questions"):
                attempt = candidate
                break
        if not attempt:
            raise RuntimeError("No answerable exam fixture was found")

        confirmed = attempt.get("results") or {}
        question = next(
            (item for item in attempt["exam"]["questions"] if item["id"] not in confirmed),
            None,
        )
        if question is None:
            api_json(
                client, "POST", f"{API_ROOT}/exam-attempts/{attempt['id']}/submit", session,
            )
            attempt = api_json(
                client, "POST", f"{API_ROOT}/exam-attempts",
                session, json={"examId": attempt["exam"]["id"]},
            )
            question = attempt["exam"]["questions"][0]

        response = sample_response(question)
        endpoint = f"{API_ROOT}/exam-attempts/{attempt['id']}/questions/{question['id']}/confirm"
        first = api_json(client, "POST", endpoint, session, json={"response": response})
        assert isinstance(first.get("isCorrect"), bool)
        assert first.get("correctAnswer") is not None
        assert str(first.get("explanation") or "").strip()

        repeated = api_json(client, "POST", endpoint, session, json={"response": response})
        assert repeated == first

        changed = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {session.token}"},
            json={"response": changed_response(question, response)},
        )
        assert changed.status_code == 409

        restored = api_json(
            client, "GET", f"{API_ROOT}/exam-attempts/{attempt['id']}", session,
        )
        assert question["id"] in restored.get("results", {})
        assert restored.get("responses", {}).get(question["id"]) == response

        api_json(
            client, "POST", f"{API_ROOT}/exam-attempts/{attempt['id']}/submit", session,
        )
        retry = api_json(
            client, "POST", f"{API_ROOT}/exam-attempts",
            session, json={"examId": attempt["exam"]["id"]},
        )
        retry_question = retry["exam"]["questions"][0]
        opposite_response = (
            changed_response(retry_question, response)
            if first["isCorrect"] else first["correctAnswer"]
        )
        opposite = api_json(
            client, "POST",
            f"{API_ROOT}/exam-attempts/{retry['id']}/questions/{retry_question['id']}/confirm",
            session, json={"response": opposite_response},
        )
        assert opposite["isCorrect"] is not first["isCorrect"]

        print({
            "confirmed": True,
            "questionType": question["question_type"],
            "correctPathVerified": first["isCorrect"] or opposite["isCorrect"],
            "incorrectPathVerified": not first["isCorrect"] or not opposite["isCorrect"],
            "judgementReturned": isinstance(first.get("isCorrect"), bool),
            "answerRevealed": first.get("correctAnswer") is not None,
            "explanationRevealed": bool(str(first.get("explanation") or "").strip()),
            "idempotent": repeated == first,
            "changedAnswerLocked": changed.status_code == 409,
            "restoredAfterReload": question["id"] in restored.get("results", {}),
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
