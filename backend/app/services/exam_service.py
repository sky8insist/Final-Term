import asyncio
from difflib import SequenceMatcher
import io
import json
import re
import textwrap
from hashlib import sha256
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services.llm_service import LLMServiceError, generate_json_async
from app.services.retrieval_service import search_subject_context
from app.services.mastery_service import record_performance
from app.services.external_search_service import ExternalSearchError, search_public_knowledge_async
from app.services.subject_service import get_subject
from app.services.export_font_service import load_export_font


def _normalize_answer(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return sorted(re.sub(r"\s+", "", str(item)).casefold() for item in values)


def _stem_key(value: object) -> str:
    return re.sub(r"\W+", "", str(value).casefold())


def _is_near_duplicate(candidate: str, existing: set[str], threshold: float = 0.9) -> bool:
    return candidate in existing or any(
        SequenceMatcher(None, candidate, prior).ratio() >= threshold
        for prior in existing if prior
    )


def grade_objective(*, question_type: str, response, correct_answer, points: float) -> dict:
    correct = _normalize_answer(response) == _normalize_answer(correct_answer)
    return {
        "earnedPoints": points if correct else 0.0, "maxPoints": points,
        "isCorrect": correct,
        "feedback": "回答正确。" if correct else "回答错误，请结合解析复习该知识点。",
        "earnedCriteria": ["答案匹配"] if correct else [],
        "missingCriteria": [] if correct else ["正确答案"],
        "errorType": None if correct else "concept_or_recall",
    }


def _get_or_create_knowledge_point(*, client, user_id: str, subject_id: str,
                                   knowledge_key: str) -> dict:
    response = client.table("knowledge_points").upsert({
        "user_id": user_id, "subject_id": subject_id,
        "knowledge_key": knowledge_key, "title": knowledge_key,
    }, on_conflict="user_id,subject_id,knowledge_key").select("*").execute()
    return response.data[0]


def _create_rubric(*, client, user_id: str, subject_id: str, question_id: str,
                   question_type: str, rubric: dict | None, points: float) -> dict | None:
    if question_type not in {"short_answer", "calculation", "essay"}:
        return None
    criteria = (rubric or {}).get("criteria") or []
    response = client.table("rubrics").insert({
        "user_id": user_id, "subject_id": subject_id,
        "name": f"question:{question_id}", "question_type": question_type,
        "version": 1, "criteria": criteria, "total_points": points,
    }).select("*").execute()
    return response.data[0]


def _validate_generated_questions(result: dict, specs: list[dict], allowed_citation_ids: set[str],
                                  forbidden_stems: set[str] | None = None,
                                  min_external_questions: int = 0) -> list[dict]:
    questions = result.get("questions") or []
    expected = {spec["questionType"]: spec["count"] for spec in specs}
    points_by_type = {spec["questionType"]: float(spec["pointsEach"]) for spec in specs}
    actual: dict[str, int] = {}
    seen: set[str] = set()
    for question in questions:
        qtype = question.get("questionType")
        actual[qtype] = actual.get(qtype, 0) + 1
        stem_key = _stem_key(question.get("stem", ""))
        if (
            not stem_key
            or _is_near_duplicate(stem_key, seen)
            or _is_near_duplicate(stem_key, forbidden_stems or set())
        ):
            raise HTTPException(status_code=502, detail="Generated exam contains empty or duplicate questions")
        seen.add(stem_key)
        if question.get("correctAnswer") is None or not str(question.get("explanation", "")).strip():
            raise HTTPException(status_code=502, detail="Generated question is missing answer or explanation")
        if not question.get("citationIds"):
            raise HTTPException(status_code=502, detail="Generated question is missing source citations")
        if any(str(citation_id) not in allowed_citation_ids for citation_id in question["citationIds"]):
            raise HTTPException(status_code=502, detail="Generated question contains an invalid source citation")
        if qtype in {"single_choice", "multiple_choice"} and len(question.get("options") or []) < 2:
            raise HTTPException(status_code=502, detail="Choice question has insufficient options")
        if qtype in {"single_choice", "multiple_choice"}:
            options = question.get("options") or []
            if len({str(option).strip() for option in options}) != len(options):
                raise HTTPException(status_code=502, detail="Choice question contains duplicate options")
            answers = question["correctAnswer"] if isinstance(question["correctAnswer"], list) else [question["correctAnswer"]]
            if any(answer not in options for answer in answers):
                raise HTTPException(status_code=502, detail="Choice answer is not present in options")
        if qtype in {"short_answer", "calculation", "essay"}:
            criteria = (question.get("rubric") or {}).get("criteria") or []
            if not criteria or any(not str(item.get("description", "")).strip() for item in criteria):
                raise HTTPException(status_code=502, detail="Subjective question is missing a fixed rubric")
            rubric_points = sum(float(item.get("points", 0)) for item in criteria)
            if abs(rubric_points - points_by_type.get(qtype, 0)) > 0.001:
                raise HTTPException(status_code=502, detail="Subjective rubric points do not match the blueprint")
    if actual != expected:
        raise HTTPException(status_code=502, detail={"message": "Generated question counts did not match blueprint", "expected": expected, "actual": actual})
    external_count = sum(
        1 for question in questions
        if any(str(value).startswith("external:") for value in question.get("citationIds", []))
    )
    if external_count < min_external_questions:
        raise HTTPException(status_code=502, detail="Generated exam did not meet the requested external-source ratio")
    return questions


async def generate_exam(*, user_id: str, payload) -> dict:
    specs = [item.model_dump(by_alias=True) for item in payload.question_types]
    total_points = sum(item.count * item.points_each for item in payload.question_types)
    question_count = sum(item.count for item in payload.question_types)
    context = await asyncio.to_thread(
        search_subject_context,
        user_id=user_id, subject_id=payload.subject_id,
        question=payload.scope or "覆盖期末考试核心知识点与易错点",
        top_k=20, material_ids=payload.material_ids,
    )
    if not context["citations"]:
        raise HTTPException(status_code=422, detail="No cited material is available for exam generation")
    min_external_questions = 0
    if payload.external_ratio > 0:
        subject = get_subject(user_id=user_id, subject_id=payload.subject_id)
        if not (settings.enable_external_knowledge or settings.enable_wikipedia_fallback) or not subject.get("externalKnowledgeEnabled", False):
            raise HTTPException(status_code=422, detail="External knowledge is not enabled for this subject")
        try:
            external_rows = await search_public_knowledge_async(payload.scope or "期末考试核心知识点")
        except ExternalSearchError as exc:
            raise HTTPException(status_code=502, detail="External research failed") from exc
        for row in external_rows:
            citation_id = "external:" + sha256(row["url"].encode("utf-8")).hexdigest()[:16]
            context["citations"].append({
                "id": citation_id, "materialId": citation_id, "filename": row["title"],
                "chunkText": row["content"], "sourceType": "external", "url": row["url"],
                "title": row["title"], "publishedAt": row.get("publishedAt"),
                "accessedAt": row["accessedAt"], "trustLevel": row["trustLevel"],
            })
        if not external_rows:
            raise HTTPException(status_code=422, detail="No usable external sources were found")
        min_external_questions = max(1, round(question_count * payload.external_ratio))
    forbidden_stems: set[str] = set()
    if payload.avoid_seen:
        client = get_supabase_client()
        existing_questions = (
            client.table("questions").select("id").eq("user_id", user_id)
            .eq("subject_id", payload.subject_id).limit(500).execute().data
        )
        ids = [row["id"] for row in existing_questions]
        if ids:
            versions = (
                client.table("question_versions").select("stem").in_("question_id", ids)
                .order("created_at", desc=True).limit(500).execute().data
            )
            forbidden_stems = {
                _stem_key(row.get("stem", ""))
                for row in versions if row.get("stem")
            }
    prompt = f"""你是一名熟悉高校命题规范的期末考试命题专家。生成严格基于证据的试卷，返回单个JSON对象：
{{"questions":[{{"questionType":"single_choice等","stem":"","options":[],"correctAnswer":[],"explanation":"","knowledgeKey":"","difficulty":"easy|medium|hard","rubric":{{"criteria":[]}},"citationIds":[]}}]}}
测试类型：{payload.assessment_type}；蓝图：{json.dumps(specs, ensure_ascii=False)}；
总体难度：{payload.difficulty}；考试时长：{payload.duration_minutes}分钟；范围：{payload.scope or '检索范围'}。
必须精确满足每种题型数量，共{question_count}题。citationIds只能来自证据中的真实编号。
课程资料证据优先于外部知识；不得使用证据之外的裸模型知识伪装成资料结论。
题目应覆盖定义理解、关系辨析、知识迁移和典型易错点，难度及计算量应与考试时长匹配。
选择题干扰项应源于常见误区且保持同一语义层级；不得使用明显荒谬或长度泄露答案的选项。
主观题 rubric.criteria 必须包含 description 与 points，评分点之和等于题目分值。
每道题必须唯一、可解、表述无歧义，并提供答案、解析、知识点、难度和真实引用。
至少 {min_external_questions} 道题引用 external: 开头的外部来源；外部内容不得覆盖课程资料中的不同表述。
不得复用的历史题干：{json.dumps(sorted(forbidden_stems)[:200], ensure_ascii=False)}
证据：{json.dumps(context['citations'], ensure_ascii=False)}"""
    allowed_citation_ids = {str(item["id"]) for item in context["citations"]}
    validation_feedback = ""
    questions: list[dict] | None = None
    for attempt in range(3):
        repair_prompt = prompt
        if validation_feedback:
            repair_prompt += f"\n上一次结果未通过质量检查：{validation_feedback}。请完整重写不合格试卷，不要只解释错误。"
        try:
            generated = await generate_json_async(repair_prompt)
        except LLMServiceError as exc:
            if attempt == 2:
                raise HTTPException(status_code=502, detail="Exam generation failed") from exc
            validation_feedback = "模型未返回有效 JSON"
            continue
        try:
            questions = _validate_generated_questions(
                generated, specs, allowed_citation_ids, forbidden_stems,
                min_external_questions,
            )
            break
        except HTTPException as exc:
            if attempt == 2:
                raise
            validation_feedback = str(exc.detail)
    if questions is None:
        raise HTTPException(status_code=502, detail="Exam generation failed quality validation")
    client = get_supabase_client()
    blueprint = client.table("exam_blueprints").insert({
        "user_id": user_id, "subject_id": payload.subject_id, "title": payload.title,
        "duration_minutes": payload.duration_minutes, "total_points": total_points,
        "specification": {"questionTypes": specs, "difficulty": payload.difficulty,
                          "scope": payload.scope, "externalRatio": payload.external_ratio,
                          "avoidSeen": payload.avoid_seen,
                          "assessmentType": payload.assessment_type,
                          "materialIds": payload.material_ids or []},
    }).select("*").execute().data[0]
    exam = client.table("exams").insert({
        "user_id": user_id, "subject_id": payload.subject_id, "blueprint_id": blueprint["id"],
        "title": payload.title, "duration_minutes": payload.duration_minutes,
        "total_points": total_points, "status": "published",
    }).select("*").execute().data[0]
    section = client.table("exam_sections").insert({
        "exam_id": exam["id"], "title": "模拟试题", "instructions": "请在规定时间内完成全部题目。",
        "sequence_index": 0, "points": total_points,
    }).select("*").execute().data[0]
    point_map = {item.question_type: item.points_each for item in payload.question_types}
    for index, item in enumerate(questions):
        knowledge_key = item.get("knowledgeKey") or "未分类"
        knowledge_point = _get_or_create_knowledge_point(
            client=client, user_id=user_id, subject_id=payload.subject_id,
            knowledge_key=knowledge_key,
        )
        question = client.table("questions").insert({
            "user_id": user_id, "subject_id": payload.subject_id,
            "question_type": item["questionType"], "knowledge_key": knowledge_key,
            "knowledge_point_id": knowledge_point["id"],
            "difficulty": item.get("difficulty", payload.difficulty),
            "source_kind": "mixed" if payload.external_ratio else "material",
        }).select("*").execute().data[0]
        rubric = _create_rubric(
            client=client, user_id=user_id, subject_id=payload.subject_id,
            question_id=question["id"], question_type=item["questionType"],
            rubric=item.get("rubric"), points=float(point_map[item["questionType"]]),
        )
        client.table("question_versions").insert({
            "question_id": question["id"], "version": 1, "stem": item["stem"],
            "options": item.get("options") or [], "correct_answer": item["correctAnswer"],
            "explanation": item["explanation"], "citations": item["citationIds"],
            "rubric": item.get("rubric"), "rubric_id": rubric["id"] if rubric else None,
            "quality": {"validated": True, "promptVersion": settings.prompt_version},
        }).execute()
        client.table("exam_questions").insert({
            "exam_id": exam["id"], "section_id": section["id"], "question_id": question["id"],
            "question_version": 1, "sequence_index": index, "points": point_map[item["questionType"]],
        }).execute()
    return get_exam(user_id=user_id, exam_id=exam["id"], include_answers=False)


def list_exams(*, user_id: str, subject_id: str) -> list[dict]:
    return get_supabase_client().table("exams").select("id,subject_id,title,version,duration_minutes,total_points,status,created_at").eq("user_id", user_id).eq("subject_id", subject_id).order("created_at", desc=True).execute().data


def list_assessment_history(*, user_id: str, subject_id: str) -> list[dict]:
    client = get_supabase_client()
    attempts = (
        client.table("exam_attempts").select("*").eq("user_id", user_id)
        .eq("subject_id", subject_id).neq("status", "in_progress")
        .order("started_at", desc=True).limit(100).execute().data
    )
    history = []
    for attempt in attempts:
        exam_rows = client.table("exams").select("*").eq("id", attempt["exam_id"]).eq("user_id", user_id).limit(1).execute().data
        if not exam_rows:
            continue
        exam = exam_rows[0]
        blueprint_rows = client.table("exam_blueprints").select("specification").eq("id", exam["blueprint_id"]).eq("user_id", user_id).limit(1).execute().data
        specification = blueprint_rows[0].get("specification", {}) if blueprint_rows else {}
        history.append({
            "attemptId": attempt["id"], "examId": exam["id"], "title": exam["title"],
            "assessmentType": specification.get("assessmentType", "mock"),
            "scope": specification.get("scope"),
            "materialIds": specification.get("materialIds", []),
            "score": float(attempt["score"]) if attempt.get("score") is not None else None,
            "maxScore": float(attempt["max_score"]) if attempt.get("max_score") is not None else None,
            "status": attempt["status"], "startedAt": attempt["started_at"],
            "submittedAt": attempt.get("submitted_at"),
        })
    return history


def export_exam(*, user_id: str, exam_id: str, export_format: str,
                include_answers: bool = False) -> tuple[bytes, str, str]:
    exam = get_exam(user_id=user_id, exam_id=exam_id, include_answers=include_answers)
    lines = [
        f"# {exam['title']}", "",
        f"- 时长：{exam['duration_minutes']} 分钟",
        f"- 总分：{float(exam['total_points']):g} 分", "",
    ]
    for index, question in enumerate(exam["questions"], start=1):
        lines.extend([f"## {index}. {question['stem']}（{question['points']:g} 分）"])
        for option in question.get("options") or []:
            lines.append(f"- {option}")
        lines.append("")
        if include_answers:
            lines.extend([
                f"**参考答案：** {question.get('correctAnswer')}",
                f"**解析：** {question.get('explanation', '')}", "",
            ])
    markdown = "\n".join(lines)
    safe_name = f"exam-{exam_id}"
    if export_format in {"markdown", "md"}:
        return markdown.encode("utf-8"), "text/markdown; charset=utf-8", f"{safe_name}.md"
    if export_format != "pdf":
        raise HTTPException(status_code=400, detail="Unsupported exam export format")
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, width=58, replace_whitespace=False) or [""])
    image = Image.new("RGB", (1240, max(1754, 60 + len(wrapped) * 34)), "white")
    draw, font = ImageDraw.Draw(image), load_export_font(20)
    for index, line in enumerate(wrapped):
        draw.text((60, 50 + index * 34), line, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, format="PDF", resolution=150)
    return output.getvalue(), "application/pdf", f"{safe_name}.pdf"


def get_exam(*, user_id: str, exam_id: str, include_answers: bool = False) -> dict:
    client = get_supabase_client()
    rows = client.table("exams").select("*").eq("id", exam_id).eq("user_id", user_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Exam not found")
    exam = rows[0]
    joins = client.table("exam_questions").select("question_id,question_version,sequence_index,points,section_id").eq("exam_id", exam_id).order("sequence_index").execute().data
    items = []
    for join in joins:
        question = client.table("questions").select("id,question_type,knowledge_key,difficulty").eq("id", join["question_id"]).limit(1).execute().data[0]
        version = client.table("question_versions").select("*").eq("question_id", question["id"]).eq("version", join["question_version"]).limit(1).execute().data[0]
        item = {**question, "stem": version["stem"], "options": version["options"],
                "sequenceIndex": join["sequence_index"], "points": float(join["points"])}
        if include_answers:
            item.update({"correctAnswer": version["correct_answer"], "explanation": version["explanation"],
                         "rubric": version.get("rubric"), "citations": version.get("citations", [])})
        items.append(item)
    return {**exam, "questions": items}


def start_attempt(*, user_id: str, exam_id: str) -> dict:
    exam = get_exam(user_id=user_id, exam_id=exam_id)
    client = get_supabase_client()
    existing = (
        client.table("exam_attempts").select("*").eq("user_id", user_id)
        .eq("exam_id", exam_id).eq("status", "in_progress")
        .order("started_at", desc=True).limit(1).execute().data
    )
    if existing:
        return get_attempt(user_id=user_id, attempt_id=existing[0]["id"])
    now = datetime.now(UTC)
    response = client.table("exam_attempts").insert({
        "user_id": user_id, "subject_id": exam["subject_id"], "exam_id": exam_id,
        "expires_at": (now + timedelta(minutes=exam["duration_minutes"])).isoformat(),
        "max_score": exam["total_points"],
    }).select("*").execute()
    return {**response.data[0], "exam": exam}


def get_attempt(*, user_id: str, attempt_id: str) -> dict:
    client = get_supabase_client()
    rows = (
        client.table("exam_attempts").select("*")
        .eq("id", attempt_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Exam attempt not found")
    attempt = rows[0]
    responses = (
        client.table("exam_responses").select("question_id,response,answered_at")
        .eq("attempt_id", attempt_id).eq("user_id", user_id).execute().data
    )
    return {
        **attempt,
        "exam": get_exam(user_id=user_id, exam_id=attempt["exam_id"], include_answers=False),
        "responses": {row["question_id"]: row["response"] for row in responses},
    }


def save_response(*, user_id: str, attempt_id: str, question_id: str, response_value) -> dict:
    client = get_supabase_client()
    rows = client.table("exam_attempts").select("*").eq("id", attempt_id).eq("user_id", user_id).limit(1).execute().data
    if not rows or rows[0]["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Exam attempt is not in progress")
    if datetime.fromisoformat(rows[0]["expires_at"].replace("Z", "+00:00")) < datetime.now(UTC):
        client.table("exam_attempts").update({"status": "expired"}).eq("id", attempt_id).execute()
        raise HTTPException(status_code=409, detail="Exam attempt has expired")
    belongs = client.table("exam_questions").select("question_id").eq("exam_id", rows[0]["exam_id"]).eq("question_id", question_id).limit(1).execute().data
    if not belongs:
        raise HTTPException(status_code=404, detail="Question is not part of this exam")
    saved = client.table("exam_responses").upsert({
        "user_id": user_id, "attempt_id": attempt_id, "question_id": question_id,
        "response": response_value,
    }, on_conflict="attempt_id,question_id").select("*").execute().data[0]
    return saved


async def _grade_subjective(item: dict, response_value) -> dict:
    prompt = f"""按固定评分量规批改主观题并只返回JSON：earnedPoints,isCorrect,feedback,earnedCriteria,missingCriteria,errorType。
满分不得超过{item['points']}。不得因表达风格扣除量规外分数。
题目：{item['stem']}\n学生答案：{response_value}\n参考答案：{item['correctAnswer']}\n量规：{json.dumps(item.get('rubric'), ensure_ascii=False)}"""
    try:
        result = await generate_json_async(prompt)
    except LLMServiceError as exc:
        raise HTTPException(status_code=502, detail="Subjective grading failed") from exc
    earned = min(max(float(result.get("earnedPoints", 0)), 0), float(item["points"]))
    return {"earnedPoints": earned, "maxPoints": float(item["points"]),
            "isCorrect": result.get("isCorrect", earned == float(item["points"])),
            "feedback": str(result.get("feedback", "")), "earnedCriteria": result.get("earnedCriteria", []),
            "missingCriteria": result.get("missingCriteria", []), "errorType": result.get("errorType")}


async def submit_attempt(*, user_id: str, attempt_id: str) -> dict:
    client = get_supabase_client()
    attempts = client.table("exam_attempts").select("*").eq("id", attempt_id).eq("user_id", user_id).limit(1).execute().data
    if not attempts or attempts[0]["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Exam attempt is not in progress")
    attempt = attempts[0]
    # Expired attempts are still graded using answers saved before the deadline.
    # save_response rejects late mutations, while submit remains idempotent-safe.
    exam = get_exam(user_id=user_id, exam_id=attempt["exam_id"], include_answers=True)
    responses = client.table("exam_responses").select("*").eq("attempt_id", attempt_id).eq("user_id", user_id).execute().data
    response_map = {row["question_id"]: row["response"] for row in responses}
    results, total = [], 0.0
    for item in exam["questions"]:
        response_value = response_map.get(item["id"], "")
        if item["question_type"] in {"single_choice", "multiple_choice", "true_false", "fill_blank"}:
            grade = grade_objective(question_type=item["question_type"], response=response_value,
                                    correct_answer=item["correctAnswer"], points=item["points"])
        else:
            grade = await _grade_subjective(item, response_value)
        total += grade["earnedPoints"]
        client.table("grading_results").upsert({
            "user_id": user_id, "attempt_id": attempt_id, "question_id": item["id"],
            "earned_points": grade["earnedPoints"], "max_points": grade["maxPoints"],
            "is_correct": grade["isCorrect"], "feedback": grade["feedback"],
            "earned_criteria": grade["earnedCriteria"], "missing_criteria": grade["missingCriteria"],
            "error_type": grade["errorType"],
        }, on_conflict="attempt_id,question_id").execute()
        if not grade["isCorrect"]:
            client.table("wrong_answers").upsert({
                "user_id": user_id, "subject_id": attempt["subject_id"], "attempt_id": attempt_id,
                "question_id": item["id"], "error_type": grade["errorType"] or "incomplete",
                "diagnosis": grade["feedback"], "next_review_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            }, on_conflict="user_id,attempt_id,question_id").execute()
        record_performance(
            user_id=user_id, subject_id=attempt["subject_id"],
            knowledge_key=item["knowledge_key"], correct=bool(grade["isCorrect"]),
            difficulty=item["difficulty"],
        )
        results.append({"questionId": item["id"], **grade, "correctAnswer": item["correctAnswer"],
                        "explanation": item["explanation"], "citations": item["citations"]})
    client.table("exam_attempts").update({
        "status": "graded", "submitted_at": datetime.now(UTC).isoformat(), "score": total,
    }).eq("id", attempt_id).eq("user_id", user_id).execute()
    return {"attemptId": attempt_id, "score": total, "maxScore": float(attempt["max_score"]), "results": results}


def list_wrong_answers(*, user_id: str, subject_id: str, resolved: bool | None = None) -> list[dict]:
    client = get_supabase_client()
    query = client.table("wrong_answers").select("*").eq("user_id", user_id).eq("subject_id", subject_id)
    if resolved is not None:
        query = query.eq("resolved", resolved)
    rows = query.order("created_at", desc=True).execute().data
    enriched = []
    for row in rows:
        questions = (
            client.table("questions").select("id,knowledge_key,current_version")
            .eq("id", row["question_id"]).eq("user_id", user_id).limit(1).execute().data
        )
        question = questions[0] if questions else {}
        versions = (
            client.table("question_versions").select("stem,correct_answer")
            .eq("question_id", row["question_id"])
            .eq("version", question.get("current_version", 1)).limit(1).execute().data
        )
        version = versions[0] if versions else {}
        responses = (
            client.table("exam_responses").select("response")
            .eq("attempt_id", row["attempt_id"]).eq("question_id", row["question_id"])
            .eq("user_id", user_id).limit(1).execute().data
        )
        enriched.append({
            **row,
            "topic": question.get("knowledge_key") or row.get("error_type") or "待复习知识点",
            "question": version.get("stem") or "题目内容暂不可用",
            "myAnswer": str(responses[0].get("response", "未作答")) if responses else "未作答",
            "correctAnswer": str(version.get("correct_answer", "请查看原试卷")),
            "reason": row.get("diagnosis") or "需要进一步复习该知识点。",
            "createdAt": row.get("created_at"),
        })
    return enriched


def resolve_wrong_answer(*, user_id: str, wrong_answer_id: str, resolved: bool) -> dict:
    response = (
        get_supabase_client().table("wrong_answers").update({"resolved": resolved})
        .eq("id", wrong_answer_id).eq("user_id", user_id).select("*").execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Wrong answer not found")
    return response.data[0]


async def generate_wrong_answer_variations(*, user_id: str, wrong_answer_id: str,
                                           count: int = 2) -> list[dict]:
    client = get_supabase_client()
    wrong_rows = client.table("wrong_answers").select("*").eq("id", wrong_answer_id).eq("user_id", user_id).limit(1).execute().data
    if not wrong_rows:
        raise HTTPException(status_code=404, detail="Wrong answer not found")
    wrong = wrong_rows[0]
    question = client.table("questions").select("*").eq("id", wrong["question_id"]).eq("user_id", user_id).limit(1).execute().data[0]
    version = client.table("question_versions").select("*").eq("question_id", question["id"]).eq("version", question["current_version"]).limit(1).execute().data[0]
    allowed = {str(value) for value in (version.get("citations") or [])}
    prompt = f"""针对错题生成 {count} 道不重复变式题，严格返回 JSON：
{{"questions":[{{"questionType":"{question['question_type']}","stem":"","options":[],"correctAnswer":null,"explanation":"","knowledgeKey":"","difficulty":"{question['difficulty']}","citationIds":[]}}]}}
一部分保持同知识点，一部分考查相邻知识点；必须可解，不得照抄原题。citationIds 只能取 {json.dumps(sorted(allowed), ensure_ascii=False)}。
原题：{version['stem']}\n错因：{wrong.get('diagnosis', '')}"""
    try:
        generated = await generate_json_async(prompt)
    except LLMServiceError as exc:
        raise HTTPException(status_code=502, detail="Variation generation failed") from exc
    variations = generated.get("questions") or []
    if len(variations) != count:
        raise HTTPException(status_code=502, detail="Variation generation returned an invalid count")
    created = []
    original_key = _stem_key(version["stem"])
    seen = {original_key}
    for item in variations:
        stem_key = _stem_key(item.get("stem", ""))
        citation_ids = {str(value) for value in item.get("citationIds", [])}
        if not stem_key or _is_near_duplicate(stem_key, seen) or not citation_ids or not citation_ids.issubset(allowed):
            raise HTTPException(status_code=502, detail="Variation failed duplicate or citation validation")
        if item.get("correctAnswer") is None or not item.get("explanation"):
            raise HTTPException(status_code=502, detail="Variation is missing an answer or explanation")
        seen.add(stem_key)
        new_question = client.table("questions").insert({
            "user_id": user_id, "subject_id": wrong["subject_id"],
            "question_type": item.get("questionType", question["question_type"]),
            "knowledge_key": item.get("knowledgeKey") or question["knowledge_key"],
            "difficulty": item.get("difficulty", question["difficulty"]),
            "source_kind": question["source_kind"],
        }).select("*").execute().data[0]
        client.table("question_versions").insert({
            "question_id": new_question["id"], "version": 1, "stem": item["stem"],
            "options": item.get("options") or [], "correct_answer": item["correctAnswer"],
            "explanation": item["explanation"], "citations": list(citation_ids),
            "quality": {"validated": True, "originWrongAnswerId": wrong_answer_id,
                        "promptVersion": settings.prompt_version},
        }).execute()
        created.append({"id": new_question["id"], "stem": item["stem"],
                        "options": item.get("options") or [], "knowledgeKey": item.get("knowledgeKey")})
    client.table("wrong_answers").update({
        "review_count": int(wrong.get("review_count", 0)) + 1,
        "next_review_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
    }).eq("id", wrong_answer_id).eq("user_id", user_id).execute()
    return created
