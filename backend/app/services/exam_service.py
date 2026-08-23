import asyncio
from difflib import SequenceMatcher
import io
import json
import math
import re
import textwrap
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services.llm_service import LLMServiceError, generate_json_async
from app.services.mastery_service import record_performance
from app.services.exam_retrieval_service import retrieve_exam_evidence
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
    if question_type == "fill_blank" and not isinstance(response, list) and isinstance(correct_answer, list):
        response_key = _normalize_answer(response)
        correct = any(response_key == _normalize_answer(candidate) for candidate in correct_answer)
    else:
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


def _question_batches(specs: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    for spec in specs:
        remaining = int(spec["count"])
        while remaining:
            count = min(remaining, settings.exam_batch_size)
            batches.append([{**spec, "count": count}])
            remaining -= count
    return batches


def _batch_evidence(citations: list[dict], batch_index: int) -> list[dict]:
    course = [item for item in citations if item.get("sourceType") != "external"]
    external = [item for item in citations if item.get("sourceType") == "external"]
    if course:
        offset = (batch_index * 3) % len(course)
        course = (course[offset:] + course[:offset])[:6]
    return course + external[:2]


async def generate_exam(*, user_id: str, payload, on_stage=None, checkpoint: dict | None = None) -> dict:
    def report(stage: str, details: dict | None = None) -> None:
        if not on_stage:
            return
        try:
            on_stage(stage, details or {})
        except TypeError:
            on_stage(stage)

    specs = [item.model_dump(by_alias=True) for item in payload.question_types if item.count > 0]
    total_points = sum(item.count * item.points_each for item in payload.question_types)
    question_count = sum(item.count for item in payload.question_types)
    topic = (payload.scope or "覆盖课程核心知识点与易错点").strip()
    report("retrieving", {"topic": topic})
    try:
        context = await retrieve_exam_evidence(
            user_id=user_id, subject_id=payload.subject_id, topic=topic,
            question_count=question_count, material_ids=payload.material_ids,
            knowledge_policy=payload.knowledge_policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not context["citations"]:
        raise HTTPException(status_code=422, detail="当前主题没有可用于命题的课程资料")

    retrieval = context["retrieval"]
    external_available = bool(retrieval.get("externalUsed"))
    external_ratio = payload.external_ratio
    if external_available and payload.knowledge_policy == "course_first":
        external_ratio = max(external_ratio, 0.2)
    elif external_available and payload.knowledge_policy == "expanded":
        external_ratio = max(external_ratio, 0.35)
    min_external_questions = min(question_count, math.ceil(question_count * external_ratio))
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
    batches = _question_batches(specs)
    stored_checkpoint = checkpoint or {}
    questions = list(stored_checkpoint.get("questions") or [])
    completed_batches = min(int(stored_checkpoint.get("completedBatches") or 0), len(batches))
    checkpoint_citations = stored_checkpoint.get("citations") or []
    if checkpoint_citations:
        known = {str(item["id"]) for item in context["citations"]}
        context["citations"].extend(item for item in checkpoint_citations if str(item.get("id")) not in known)
    generated_stems = {_stem_key(item.get("stem", "")) for item in questions}
    external_remaining = max(0, min_external_questions - sum(
        1 for item in questions if any(str(value).startswith("external:") for value in item.get("citationIds", []))
    ))
    for batch_index, batch_specs in enumerate(batches):
        if batch_index < completed_batches:
            continue
        batch_count = sum(int(item["count"]) for item in batch_specs)
        remaining_batches = len(batches) - batch_index
        batch_external = min(batch_count, math.ceil(external_remaining / remaining_batches)) if external_remaining else 0
        evidence = _batch_evidence(context["citations"], batch_index)
        compact_evidence = [{
            "id": item.get("id"), "sourceType": item.get("sourceType", "material"),
            "filename": item.get("filename"), "pageNumber": item.get("pageNumber"),
            "relevanceScore": item.get("relevanceScore"), "importanceScore": item.get("importanceScore"),
            "chunkText": str(item.get("chunkText") or "")[:1200],
        } for item in evidence]
        prompt = f"""你是高校课程练习命题专家。只返回一个JSON对象：
{{"questions":[{{"questionType":"single_choice|multiple_choice|true_false|fill_blank|short_answer|calculation|essay","stem":"","options":[],"correctAnswer":[],"explanation":"","knowledgeKey":"","difficulty":"easy|medium|hard","citationIds":[],"rubric":{{"criteria":[{{"description":"","points":0}}]}}}}]}}
练习主题：{topic}；本批蓝图：{json.dumps(batch_specs, ensure_ascii=False)}；难度：{payload.difficulty}。
必须精确生成本批 {batch_count} 道题，题型和数量必须与蓝图一致。
每题必须有答案、解析、知识点和真实 citationIds；citationIds 只能选自证据 id。
课程资料是标准答案的首要依据；公开知识只用于补充背景、案例和覆盖，不得覆盖课程资料口径。
本批至少 {batch_external} 道题引用 external: 开头的公开来源。
选择题选项不得重复，正确答案必须原样存在于 options；干扰项应来自常见误区。
填空题的 correctAnswer 可以是字符串或包含多个等价答案的数组。
short_answer、calculation、essay 必须提供固定 rubric.criteria；每项包含 description 和 points，points 总和必须严格等于蓝图中的 pointsEach。
题目应覆盖定义、关系、应用或易错点，避免仅换词重复。
不得复用的相似题干：{json.dumps(sorted((forbidden_stems | generated_stems))[:80], ensure_ascii=False)}
证据：{json.dumps(compact_evidence, ensure_ascii=False)}"""
        feedback = ""
        batch_questions = None
        for attempt in range(settings.exam_batch_retries + 1):
            report("generating", {
                "batch": batch_index + 1, "batchCount": len(batches),
                "completedQuestions": len(questions), "totalQuestions": question_count,
            })
            try:
                generated = await generate_json_async(
                    prompt + (f"\n上次结果未通过检查：{feedback}。请完整重写本批。" if feedback else ""),
                    timeout=settings.exam_batch_timeout_seconds,
                )
                report("validating", {
                    "batch": batch_index + 1, "batchCount": len(batches),
                    "completedQuestions": len(questions), "totalQuestions": question_count,
                })
                batch_questions = _validate_generated_questions(
                    generated, batch_specs, {str(item["id"]) for item in evidence},
                    forbidden_stems | generated_stems, batch_external,
                )
                break
            except LLMServiceError as exc:
                feedback = "模型响应超时或不可用"
                if attempt >= settings.exam_batch_retries:
                    status_code = 504 if "timed out" in str(exc).casefold() else 502
                    detail = "题目生成模型响应超时，失败批次已重试" if status_code == 504 else "题目生成模型调用失败"
                    raise HTTPException(status_code=status_code, detail=detail) from exc
            except HTTPException as exc:
                feedback = str(exc.detail)
                if attempt >= settings.exam_batch_retries:
                    raise
        if batch_questions is None:
            raise HTTPException(status_code=502, detail="题目批次生成失败")
        questions.extend(batch_questions)
        generated_stems.update(_stem_key(item.get("stem", "")) for item in batch_questions)
        external_remaining = max(0, external_remaining - batch_external)
        report("generating", {
            "batch": batch_index + 1, "batchCount": len(batches),
            "completedQuestions": len(questions), "totalQuestions": question_count,
            "checkpoint": {
                "topic": topic, "completedBatches": batch_index + 1,
                "questions": questions, "citations": context["citations"],
            },
        })

    _validate_generated_questions(
        {"questions": questions}, specs, {str(item["id"]) for item in context["citations"]},
        forbidden_stems, min_external_questions,
    )
    report("saving", {"completedQuestions": len(questions), "totalQuestions": question_count})
    client = get_supabase_client()
    blueprint = client.table("exam_blueprints").insert({
        "user_id": user_id, "subject_id": payload.subject_id, "title": payload.title,
        "duration_minutes": payload.duration_minutes, "total_points": total_points,
        "specification": {"questionTypes": specs, "difficulty": payload.difficulty,
                          "scope": payload.scope, "externalRatio": external_ratio,
                          "knowledgePolicy": payload.knowledge_policy,
                          "avoidSeen": payload.avoid_seen,
                          "assessmentType": payload.assessment_type,
                          "materialIds": payload.material_ids or [],
                          "retrieval": retrieval,
                          "evidence": [{
                              "id": item.get("id"), "sourceType": item.get("sourceType", "material"),
                              "sourceName": item.get("filename"), "pageNumber": item.get("pageNumber"),
                              "url": item.get("url"), "relevanceScore": item.get("relevanceScore"),
                              "importanceScore": item.get("importanceScore"),
                          } for item in context["citations"]]},
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
            "source_kind": "mixed" if retrieval.get("externalUsed") else "material",
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
    result = get_exam(user_id=user_id, exam_id=exam["id"], include_answers=False)
    result["generation"] = {
        "knowledgePolicy": payload.knowledge_policy,
        "retrieval": retrieval,
        "evidence": blueprint["specification"]["evidence"],
    }
    return result


def list_exams(*, user_id: str, subject_id: str) -> list[dict]:
    client = get_supabase_client()
    rows = client.table("exams").select(
        "id,subject_id,blueprint_id,title,version,duration_minutes,total_points,status,created_at"
    ).eq("user_id", user_id).eq("subject_id", subject_id).order("created_at", desc=True).execute().data
    if not rows:
        return []
    exam_ids = [row["id"] for row in rows]
    joins = client.table("exam_questions").select("exam_id").in_("exam_id", exam_ids).execute().data
    counts: dict[str, int] = {}
    for join in joins:
        counts[str(join["exam_id"])] = counts.get(str(join["exam_id"]), 0) + 1
    blueprint_ids = [row["blueprint_id"] for row in rows if row.get("blueprint_id")]
    blueprint_rows = client.table("exam_blueprints").select("id,specification").in_("id", blueprint_ids).execute().data if blueprint_ids else []
    specifications = {str(item["id"]): item.get("specification") or {} for item in blueprint_rows}
    for row in rows:
        spec = specifications.get(str(row.get("blueprint_id")), {})
        row["question_count"] = counts.get(str(row["id"]), 0)
        row["question_types"] = [
            item.get("questionType") for item in spec.get("questionTypes", []) if item.get("questionType")
        ]
    return rows


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
    generation = None
    if exam.get("blueprint_id"):
        try:
            blueprint_rows = (
                client.table("exam_blueprints").select("specification")
                .eq("id", exam["blueprint_id"]).eq("user_id", user_id).limit(1).execute().data
            )
            if blueprint_rows:
                specification = blueprint_rows[0].get("specification") or {}
                generation = {
                    "knowledgePolicy": specification.get("knowledgePolicy", "course_only"),
                    "retrieval": specification.get("retrieval") or {},
                    "evidence": specification.get("evidence") or [],
                }
        except Exception:
            generation = None
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
    return {**exam, "question_count": len(items), "questions": items, "generation": generation}


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
    grading_rows = (
        client.table("grading_results").select("*")
        .eq("attempt_id", attempt_id).eq("user_id", user_id).execute().data
    )
    confirmed_results = {}
    if grading_rows:
        answer_exam = get_exam(user_id=user_id, exam_id=attempt["exam_id"], include_answers=True)
        answer_map = {item["id"]: item for item in answer_exam["questions"]}
        for row in grading_rows:
            item = answer_map.get(row["question_id"])
            if item:
                confirmed_results[row["question_id"]] = _grading_payload(row, item)
    return {
        **attempt,
        "exam": get_exam(user_id=user_id, exam_id=attempt["exam_id"], include_answers=False),
        "responses": {row["question_id"]: row["response"] for row in responses},
        "results": confirmed_results,
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
    confirmed = (
        client.table("grading_results").select("id").eq("attempt_id", attempt_id)
        .eq("question_id", question_id).eq("user_id", user_id).limit(1).execute().data
    )
    if confirmed:
        raise HTTPException(status_code=409, detail="Confirmed answer cannot be changed")
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


def _grading_payload(row: dict, item: dict) -> dict:
    return {
        "questionId": item["id"],
        "earnedPoints": float(row["earned_points"]),
        "maxPoints": float(row["max_points"]),
        "isCorrect": bool(row["is_correct"]),
        "feedback": row.get("feedback") or "",
        "earnedCriteria": row.get("earned_criteria") or [],
        "missingCriteria": row.get("missing_criteria") or [],
        "errorType": row.get("error_type"),
        "correctAnswer": item["correctAnswer"],
        "explanation": item["explanation"],
        "citations": item.get("citations") or [],
    }


def _record_grade(*, client, user_id: str, attempt: dict, item: dict, grade: dict) -> dict:
    row = client.table("grading_results").upsert({
        "user_id": user_id, "attempt_id": attempt["id"], "question_id": item["id"],
        "earned_points": grade["earnedPoints"], "max_points": grade["maxPoints"],
        "is_correct": grade["isCorrect"], "feedback": grade["feedback"],
        "earned_criteria": grade["earnedCriteria"], "missing_criteria": grade["missingCriteria"],
        "error_type": grade["errorType"],
    }, on_conflict="attempt_id,question_id").select("*").execute().data[0]
    record_performance(
        user_id=user_id, subject_id=attempt["subject_id"],
        knowledge_key=item["knowledge_key"], correct=bool(grade["isCorrect"]),
        difficulty=item["difficulty"],
    )
    return row


async def confirm_response(*, user_id: str, attempt_id: str, question_id: str,
                           response_value) -> dict:
    client = get_supabase_client()
    attempts = (
        client.table("exam_attempts").select("*").eq("id", attempt_id)
        .eq("user_id", user_id).limit(1).execute().data
    )
    if not attempts:
        raise HTTPException(status_code=404, detail="Exam attempt not found")
    attempt = attempts[0]
    exam = get_exam(user_id=user_id, exam_id=attempt["exam_id"], include_answers=True)
    item = next((question for question in exam["questions"] if question["id"] == question_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Question is not part of this exam")
    existing = (
        client.table("grading_results").select("*").eq("attempt_id", attempt_id)
        .eq("question_id", question_id).eq("user_id", user_id).limit(1).execute().data
    )
    if existing:
        saved_rows = (
            client.table("exam_responses").select("response").eq("attempt_id", attempt_id)
            .eq("question_id", question_id).eq("user_id", user_id).limit(1).execute().data
        )
        saved_response = saved_rows[0]["response"] if saved_rows else None
        if _normalize_answer(saved_response) != _normalize_answer(response_value):
            raise HTTPException(status_code=409, detail="Confirmed answer cannot be changed")
        return _grading_payload(existing[0], item)
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Exam attempt is not in progress")
    save_response(
        user_id=user_id, attempt_id=attempt_id,
        question_id=question_id, response_value=response_value,
    )
    if item["question_type"] in {"single_choice", "multiple_choice", "true_false", "fill_blank"}:
        grade = grade_objective(
            question_type=item["question_type"], response=response_value,
            correct_answer=item["correctAnswer"], points=item["points"],
        )
    else:
        grade = await _grade_subjective(item, response_value)
    row = _record_grade(client=client, user_id=user_id, attempt=attempt, item=item, grade=grade)
    return _grading_payload(row, item)


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
    existing_rows = client.table("grading_results").select("*").eq("attempt_id", attempt_id).eq("user_id", user_id).execute().data
    existing_map = {row["question_id"]: row for row in existing_rows}
    results, total = [], 0.0
    for item in exam["questions"]:
        if item["id"] in existing_map:
            result = _grading_payload(existing_map[item["id"]], item)
            total += result["earnedPoints"]
            results.append(result)
            continue
        response_value = response_map.get(item["id"], "")
        if item["question_type"] in {"single_choice", "multiple_choice", "true_false", "fill_blank"}:
            grade = grade_objective(question_type=item["question_type"], response=response_value,
                                    correct_answer=item["correctAnswer"], points=item["points"])
        else:
            grade = await _grade_subjective(item, response_value)
        total += grade["earnedPoints"]
        row = _record_grade(client=client, user_id=user_id, attempt=attempt, item=item, grade=grade)
        results.append(_grading_payload(row, item))
    client.table("exam_attempts").update({
        "status": "graded", "submitted_at": datetime.now(UTC).isoformat(), "score": total,
    }).eq("id", attempt_id).eq("user_id", user_id).execute()
    return {"attemptId": attempt_id, "score": total, "maxScore": float(attempt["max_score"]), "results": results}
