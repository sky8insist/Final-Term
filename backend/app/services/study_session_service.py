from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.models.study_session import SessionAction, SessionCreate
from app.services.course_service import _owned

LABELS = {"notes": "阅读课程笔记", "socratic": "用自己的语言解释", "flashcards": "主动回忆闪卡",
          "quiz": "知识点测验", "mastery_check": "检查掌握度与下一步", "remediation": "针对错误重新学习"}


def _topic_state(user_id: str, session: dict) -> dict:
    from app.services.learner_state_service import list_states
    state = next((row for row in list_states(user_id=user_id, subject_id=session["subject_id"])["topics"]
                  if row["knowledgePointId"] == session["knowledge_point_id"]), None)
    if state is None: raise HTTPException(409, "知识点已归档，请恢复后继续或结束会话")
    return state


def build_steps(minutes: int) -> list[dict]:
    kinds = list(LABELS)[:5]
    allocations = [max(1, int(minutes * weight)) for weight in [0.3, 0.2, 0.15, 0.3, 0.05]]
    allocations[0] += minutes - sum(allocations)
    return [{"id": str(uuid4()), "kind": kind, "title": LABELS[kind], "estimated_minutes": amount,
             "sequence_index": index, "status": "pending", "output": {}}
            for index, (kind, amount) in enumerate(zip(kinds, allocations))]


def _save(user_id: str, session: dict, expected: int | None) -> dict:
    try:
        result = get_supabase_client().rpc("save_guided_session", {
            "p_user_id": user_id, "p_values": session, "p_expected_version": expected,
        }).execute().data
    except Exception as exc:
        if getattr(exc, "code", None) in {"40001", "23505"}:
            raise HTTPException(409, "学习会话已更新，请刷新后继续") from exc
        if getattr(exc, "code", None) == "22023":
            raise HTTPException(409, "推荐已失效或与当前知识点不符，请刷新建议或直接创建学习会话") from exc
        raise
    saved = result[0] if isinstance(result, list) else result
    return {**saved, "steps": session["steps"]}


def get_session(*, user_id: str, session_id: str) -> dict:
    client = get_supabase_client()
    rows = client.table("study_sessions").select("*").eq("user_id", user_id).eq("id", session_id).limit(1).execute().data
    if not rows: raise HTTPException(404, "学习会话不存在")
    steps = (client.table("study_session_steps").select("*").eq("user_id", user_id)
             .eq("session_id", session_id).order("sequence_index").execute().data)
    return {**rows[0], "steps": steps}


def list_sessions(*, user_id: str, subject_id: str) -> list[dict]:
    from app.services.subject_service import get_subject
    get_subject(user_id=user_id, subject_id=subject_id)
    return (get_supabase_client().table("study_sessions").select("id,goal,status,version,current_step,created_at")
            .eq("user_id", user_id).eq("subject_id", subject_id).order("created_at", desc=True).limit(30).execute().data)


def create_session(*, user_id: str, payload: SessionCreate) -> dict:
    subject_id, topic_id, session_id = str(payload.subject_id), str(payload.knowledge_point_id), str(payload.request_id)
    topic = _owned(table="knowledge_points", row_id=topic_id, user_id=user_id, subject_id=subject_id)
    if topic.get("archived"): raise HTTPException(409, "请先恢复已归档的知识点")
    if payload.exam_event_id:
        event = _owned(table="exam_events", row_id=str(payload.exam_event_id), user_id=user_id, subject_id=subject_id)
        maps = (get_supabase_client().table("exam_topic_map").select("knowledge_point_id").eq("user_id", user_id)
                .eq("exam_event_id", event["id"]).eq("knowledge_point_id", topic_id).execute().data)
        if event["status"] != "active" or not maps: raise HTTPException(422, "知识点不属于该活动考试范围")
    else: event = None
    from app.services.learner_state_service import list_states
    before = next(row for row in list_states(user_id=user_id, subject_id=subject_id)["topics"] if row["knowledgePointId"] == topic_id)
    session = {"id": session_id, "subject_id": subject_id, "knowledge_point_id": topic_id,
               "exam_event_id": str(payload.exam_event_id) if payload.exam_event_id else None,
               "goal": f"掌握 {topic['title']}", "status": "planned", "current_step": 0, "minutes": payload.minutes,
               "context": {"topicTitle": topic["title"], "knowledgeKey": topic["knowledge_key"],
                           "learnerStateBefore": before, "examGoal": event,
                           "recommendationId": str(payload.recommendation_id) if payload.recommendation_id else None,
                           "algorithmVersion": "guided-session-v1"}, "steps": build_steps(payload.minutes)}
    try: return _save(user_id, session, None)
    except HTTPException as exc:
        if exc.status_code != 409: raise
        existing = get_session(user_id=user_id, session_id=session_id)
        if existing["knowledge_point_id"] != topic_id or existing["subject_id"] != subject_id:
            raise HTTPException(409, "请求编号已用于另一个会话") from exc
        return existing


async def message(*, user_id: str, session_id: str, text: str) -> dict:
    session = get_session(user_id=user_id, session_id=session_id)
    step = session["steps"][session["current_step"]] if session["current_step"] < len(session["steps"]) else None
    if session["status"] != "active" or not step or step["kind"] != "socratic" or step["status"] != "ready":
        raise HTTPException(409, "当前步骤不接受对话；测验步骤请先独立作答")
    from app.models.assistant import AssistantMessageRequest
    from app.services.assistant_service import handle_message
    return await handle_message(user_id=user_id, payload=AssistantMessageRequest(
        subjectId=session["subject_id"], sessionId=session_id, message=text, role="socratic",
        interactionId=(step["output"].get("interaction") or {}).get("id"), guidedSessionId=session_id))


def quiz_exam_id(user_id: str, step: dict) -> str:
    from app.services.task_service import get_task
    task = get_task(user_id=user_id, task_id=step["output"]["taskId"])
    if task["status"] != "succeeded":
        raise HTTPException(409, task.get("errorMessage") or "测验仍在生成，请稍后继续")
    return str(task["metadata"]["examId"])


def quiz_attempt(*, user_id: str, session_id: str) -> dict:
    session = get_session(user_id=user_id, session_id=session_id)
    if session["status"] != "active": raise HTTPException(409, "学习会话尚未开始或已结束")
    step = session["steps"][session["current_step"]]
    if step["kind"] != "quiz" or step["status"] != "ready": raise HTTPException(409, "当前没有可作答的测验")
    exam_id = quiz_exam_id(user_id, step)
    from app.services.exam_service import get_attempt, start_attempt
    attempts = (get_supabase_client().table("exam_attempts").select("id").eq("user_id", user_id)
                .eq("exam_id", exam_id).order("started_at", desc=True).limit(1).execute().data)
    return get_attempt(user_id=user_id, attempt_id=attempts[0]["id"]) if attempts else start_attempt(user_id=user_id, exam_id=exam_id)


async def _execute(user_id: str, session: dict, step: dict) -> dict:
    topic = session["context"]["topicTitle"]
    if step["kind"] in {"notes", "remediation"}:
        from app.services.rag_service import answer_with_rag
        output = await answer_with_rag(user_id=user_id, subject_id=session["subject_id"], session_id=session["id"],
            question=f"请根据课程资料讲解 {topic} 的定义、关键条件、常见误解与一个例子。")
        if not output.get("citations") or not output.get("generation", {}).get("grounded"):
            raise HTTPException(422, "课程证据不足，请先补充资料，不能把无来源笔记记作有效学习")
        return output
    if step["kind"] == "socratic":
        from app.models.assistant import AssistantMessageRequest
        from app.services.assistant_service import handle_message
        output = await handle_message(user_id=user_id, payload=AssistantMessageRequest(
            subjectId=session["subject_id"], sessionId=session["id"], role="socratic",
            message=f"请围绕 {topic} 提出一个让我独立解释的苏格拉底问题，暂时不要给答案。"))
        interaction = output.get("interaction")
        if not isinstance(interaction, dict) or not interaction.get("id"):
            raise HTTPException(422, "未保存可追问的问题，请重试准备活动")
        return output
    if step["kind"] == "flashcards":
        from app.services.artifact_service import generate_artifact
        return await generate_artifact(user_id=user_id, subject_id=session["subject_id"], artifact_type="flashcards",
                                       scope=topic, material_ids=None, mode="knowledge", count=5,
                                       knowledge_point_id=session["knowledge_point_id"])
    if step["kind"] == "quiz":
        from app.models.exam import ExamGenerateRequest
        from app.services.exam_generation_service import create_generation_task
        from app.worker.tasks import generate_exam
        payload = ExamGenerateRequest(subjectId=session["subject_id"], title=f"{topic} · 引导测验", scope=topic,
            knowledgePointId=session["knowledge_point_id"], assessmentType="practice", assessmentMode="adaptive",
            durationMinutes=30, avoidSeen=False, questionTypes=[{"questionType": "single_choice", "count": 5, "pointsEach": 2}])
        task = create_generation_task(user_id=user_id, payload=payload)
        if task["status"] == "queued": generate_exam.delay(task["id"])
        return {"taskId": task["id"]}
    return {"learnerState": _topic_state(user_id, session)}


async def act(*, user_id: str, session_id: str, payload: SessionAction) -> dict:
    session = get_session(user_id=user_id, session_id=session_id)
    if session["version"] != payload.version: raise HTTPException(409, "会话版本已变化，请刷新")
    if session["status"] in {"completed", "cancelled"}: raise HTTPException(409, "会话已结束")
    if payload.action == "cancel":
        session["status"] = "cancelled"
        return _save(user_id, session, payload.version)
    if session["status"] == "planned":
        if payload.action == "edit":
            if sum(step.estimated_minutes for step in payload.steps) > session["minutes"]:
                raise HTTPException(422, "步骤总时间超过会话预算")
            session["steps"] = [{"id": str(uuid4()), "sequence_index": i, "kind": item.kind,
                "estimated_minutes": item.estimated_minutes, "title": LABELS[item.kind], "status": "pending", "output": {}}
                for i, item in enumerate(payload.steps)]
        elif payload.action == "accept": session["status"] = "active"
        else: raise HTTPException(409, "请先确认学习计划")
        return _save(user_id, session, payload.version)
    if payload.action in {"edit", "accept"}: raise HTTPException(409, "执行中的计划不能覆盖已有步骤")
    step = session["steps"][session["current_step"]]
    if payload.action == "execute":
        if step["status"] == "ready": return session
        if step["status"] == "running":
            started = datetime.fromisoformat(step["output"]["startedAt"])
            if started > datetime.now(UTC) - timedelta(minutes=10): raise HTTPException(409, "当前步骤正在准备，请稍后刷新")
        step.update(status="running", output={"startedAt": datetime.now(UTC).isoformat()})
        claimed = _save(user_id, session, payload.version)
        step = claimed["steps"][claimed["current_step"]]
        try:
            output = await _execute(user_id, claimed, step)
        except Exception:
            step.update(status="pending", output={"error": "步骤准备失败，可重试"})
            try: _save(user_id, claimed, claimed["version"])
            except HTTPException: pass
            raise
        step.update(status="ready", output=output)
        return _save(user_id, claimed, claimed["version"])
    if step["status"] == "running": raise HTTPException(409, "不能跳过正在准备的步骤")
    if payload.action == "skip":
        if step["kind"] in {"quiz", "mastery_check"}: raise HTTPException(409, "评估与掌握检查不能跳过")
        step["status"] = "skipped"
    elif payload.action == "complete":
        if step["status"] != "ready": raise HTTPException(409, "请先准备并完成当前活动")
        if step["kind"] == "quiz":
            if not payload.attempt_id: raise HTTPException(422, "需要实际测验记录")
            from app.services.exam_service import get_attempt
            attempt = get_attempt(user_id=user_id, attempt_id=str(payload.attempt_id))
            if attempt["exam_id"] != quiz_exam_id(user_id, step) or attempt["status"] != "graded" or attempt["subject_id"] != session["subject_id"]:
                raise HTTPException(409, "测验记录尚未完成或不属于当前步骤")
            step["output"]["attemptId"] = attempt["id"]
            step["output"]["scoreRatio"] = float(attempt["score"] or 0) / max(float(attempt["max_score"]), 1)
            repairs = sum(item["kind"] == "remediation" for item in session["steps"])
            if step["output"]["scoreRatio"] < 0.8 and repairs < 2:
                extras = [{"id": str(uuid4()), "kind": kind, "title": LABELS[kind], "estimated_minutes": 5,
                           "status": "pending", "output": {}} for kind in ["remediation", "quiz"]]
                session["steps"][session["current_step"] + 1:session["current_step"] + 1] = extras
        elif step["kind"] == "socratic":
            interaction = step["output"].get("interaction") or {}
            rows = (get_supabase_client().table("learning_interactions").select("status").eq("user_id", user_id)
                    .eq("session_id", session_id).eq("id", interaction.get("id", str(uuid4()))).execute().data)
            if not rows or rows[0]["status"] != "completed": raise HTTPException(409, "解释尚未通过追问评估，可以继续作答或跳过")
        elif step["kind"] == "flashcards":
            from app.services.flashcard_service import queue
            cards = queue(user_id=user_id, subject_id=session["subject_id"],
                          artifact_id=step["output"]["id"], include_future=True, limit=200)["cards"]
            reviewed = {card["card_id"] for card in cards if card["state"]["review_count"] > 0}
            expected = {str(card.get("id") or f"legacy-{i + 1}") for i, card in enumerate(step["output"]["content"]["cards"])}
            if not expected or not expected.issubset(reviewed):
                raise HTTPException(409, "请先回忆并评价每张闪卡")
        elif step["kind"] in {"notes", "remediation"}:
            from app.services.learner_state_service import mark_covered
            mark_covered(user_id=user_id, subject_id=session["subject_id"], topic_id=session["knowledge_point_id"])
        step["status"] = "completed"
    else: raise HTTPException(422, "不支持的步骤操作")
    for i, item in enumerate(session["steps"]): item["sequence_index"] = i
    session["current_step"] += 1
    if session["current_step"] >= len(session["steps"]):
        session["status"] = "completed"
        from app.services.recommendation_service import next_actions
        after = _topic_state(user_id, session)
        session["summary"] = {"before": session["context"]["learnerStateBefore"], "after": after,
                              "nextActions": next_actions(user_id=user_id, subject_id=session["subject_id"])["actions"],
                              "skippedSteps": sum(item["status"] == "skipped" for item in session["steps"]),
                              "extraMinutes": sum(item["estimated_minutes"] for item in session["steps"]) - session["minutes"]}
    return _save(user_id, session, payload.version)
