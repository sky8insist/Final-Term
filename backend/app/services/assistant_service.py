from uuid import uuid4

from app.agents.router_agent import route_intent
from app.config.settings import settings
from app.models.assistant import AssistantMessageRequest
from app.services import hermes_memory_service, rag_service
from app.services import memory_service
from app.services import artifact_service, exam_service, mastery_service, study_plan_service
from app.models.exam import ExamGenerateRequest, QuestionTypeSpec
import re
from app.services.role_service import recommend_role
from app.services.subject_service import get_subject


async def handle_message(*, user_id: str, payload: AssistantMessageRequest) -> dict:
    decision = await route_intent(payload.message.strip())
    profile = hermes_memory_service.get_profile(user_id=user_id)
    role_key, role = recommend_role(requested=payload.role, profile=profile, intent=decision.primary_intent)
    trace_id = str(uuid4())
    if decision.needs_clarification:
        clarification = decision.clarification_question or "请补充你想复习的范围和目标。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id,
            question=payload.message, answer=clarification, citations=[],
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]},
            "answer": clarification,
            "citations": [], "artifacts": [], "memoryUpdates": [],
            "suggestedActions": role["suggestions"], "traceId": trace_id,
            "needsClarification": True, "messageId": message["id"],
        }

    artifact_map = {
        "generate_outline": "outline", "generate_mind_map": "mind_map",
        "generate_flashcards": "flashcards",
    }
    if decision.primary_intent in artifact_map:
        artifact = await artifact_service.generate_artifact(
            user_id=user_id, subject_id=payload.subject_id,
            artifact_type=artifact_map[decision.primary_intent], scope=payload.message,
            material_ids=payload.material_ids, mode="knowledge", count=20,
        )
        answer_text = f"已生成《{artifact['title']}》，你可以继续编辑并导出。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=answer_text, citations=artifact.get("citations", []),
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
            "citations": artifact.get("citations", []),
            "artifacts": [{"id": artifact["id"], "type": artifact["artifact_type"], "title": artifact["title"]}],
            "memoryUpdates": [], "suggestedActions": ["打开并编辑产物", "导出产物"],
            "traceId": trace_id, "messageId": message["id"], "needsClarification": False,
        }

    if decision.primary_intent == "generate_exam":
        exam_payload = ExamGenerateRequest(
            subjectId=payload.subject_id, title="AI 模拟试卷", durationMinutes=60,
            difficulty="medium", questionTypes=[
                QuestionTypeSpec(questionType="single_choice", count=5, pointsEach=4),
                QuestionTypeSpec(questionType="short_answer", count=2, pointsEach=10),
            ], scope=payload.message, materialIds=payload.material_ids,
        )
        exam = await exam_service.generate_exam(user_id=user_id, payload=exam_payload)
        answer_text = f"已生成《{exam['title']}》，共 {len(exam['questions'])} 题，限时 {exam['duration_minutes']} 分钟。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=answer_text, citations=[],
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
            "citations": [], "artifacts": [{"id": exam["id"], "type": "exam", "title": exam["title"]}],
            "memoryUpdates": [], "suggestedActions": ["开始模拟考试"],
            "traceId": trace_id, "messageId": message["id"], "needsClarification": False,
        }

    if decision.primary_intent == "generate_practice":
        practice_payload = ExamGenerateRequest(
            subjectId=payload.subject_id, title="AI 专项练习", durationMinutes=30,
            difficulty="medium", questionTypes=[
                QuestionTypeSpec(questionType="single_choice", count=3, pointsEach=5),
                QuestionTypeSpec(questionType="short_answer", count=2, pointsEach=10),
            ], scope=payload.message, materialIds=payload.material_ids,
        )
        practice = await exam_service.generate_exam(user_id=user_id, payload=practice_payload)
        answer_text = f"已生成《{practice['title']}》，共 {len(practice['questions'])} 题。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=answer_text, citations=[],
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
            "citations": [], "artifacts": [{"id": practice["id"], "type": "practice", "title": practice["title"]}],
            "memoryUpdates": [], "suggestedActions": ["开始专项练习"],
            "traceId": trace_id, "messageId": message["id"], "needsClarification": False,
        }

    if decision.primary_intent == "review_wrong_answers":
        wrong = exam_service.list_wrong_answers(
            user_id=user_id, subject_id=payload.subject_id, resolved=False,
        )
        if wrong:
            counts: dict[str, int] = {}
            for item in wrong:
                key = item.get("error_type") or "未分类"
                counts[key] = counts.get(key, 0) + 1
            distribution = "、".join(f"{key} {value}题" for key, value in counts.items())
            answer_text = f"当前有 {len(wrong)} 道未解决错题；错误分布：{distribution}。建议先处理重复最多的错误类型。"
        else:
            answer_text = "当前没有未解决错题。完成一次练习后，我会在这里汇总错因。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=answer_text, citations=[],
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
            "citations": [], "artifacts": [], "memoryUpdates": [],
            "suggestedActions": ["打开错题本", "生成同类变式题"],
            "traceId": trace_id, "messageId": message["id"], "needsClarification": False,
        }

    if decision.primary_intent == "grade_answer":
        clarification = "请在模拟考试页面选择对应试卷并提交作答；评分必须绑定具体题目和固定评分量规。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=clarification, citations=[],
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": clarification,
            "citations": [], "artifacts": [], "memoryUpdates": [],
            "suggestedActions": ["打开模拟考试"], "traceId": trace_id,
            "messageId": message["id"], "needsClarification": True,
        }

    if decision.primary_intent == "show_progress":
        mastery = mastery_service.list_mastery(user_id=user_id, subject_id=payload.subject_id)
        weakest = sorted(mastery, key=lambda item: item.get("mastery", 0.5))[:5]
        answer_text = "当前薄弱知识点：" + ("、".join(
            f"{item['knowledge_key']}（{round(float(item['mastery']) * 100)}%）" for item in weakest
        ) if weakest else "尚无足够练习数据，请先完成一次练习。")
        message = memory_service.record_qa_history(user_id=user_id, subject_id=payload.subject_id,
                                                   question=payload.message, answer=answer_text, citations=[],
                                                   session_id=payload.session_id)
        return {"intent": decision.primary_intent, "intentConfidence": decision.confidence,
                "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
                "citations": [], "artifacts": [], "memoryUpdates": [],
                "suggestedActions": ["生成薄弱点练习", "生成复习计划"],
                "traceId": trace_id, "messageId": message["id"], "needsClarification": False}

    if decision.primary_intent == "build_study_plan":
        date_match = re.search(r"20\d{2}-\d{2}-\d{2}", payload.message)
        exam_date = date_match.group(0) if date_match else profile.get("examDate")
        if exam_date:
            plan = study_plan_service.generate_plan(
                user_id=user_id, subject_id=payload.subject_id, exam_date=exam_date,
                daily_minutes=int(profile.get("dailyMinutes") or 60), title="AI 冲刺复习计划",
            )
            answer_text = f"已生成复习计划，共 {len(plan['tasks'])} 个任务，考试日期 {exam_date}。"
            artifact_items = [{"id": plan["plan"]["id"], "type": "study_plan", "title": plan["plan"]["title"]}]
        else:
            answer_text = "请告诉我考试日期（YYYY-MM-DD），或先在学习画像中设置考试日期。"
            artifact_items = []
        message = memory_service.record_qa_history(user_id=user_id, subject_id=payload.subject_id,
                                                   question=payload.message, answer=answer_text, citations=[],
                                                   session_id=payload.session_id)
        return {"intent": decision.primary_intent, "intentConfidence": decision.confidence,
                "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
                "citations": [], "artifacts": artifact_items, "memoryUpdates": [],
                "suggestedActions": ["查看今日任务"], "traceId": trace_id,
                "messageId": message["id"], "needsClarification": not bool(exam_date)}

    # Artifact/exam/plan intents are routed through the same grounded RAG path
    # until their specialized generators run in later stages.
    question = payload.message
    active_skills = hermes_memory_service.list_active_skills(
        user_id=user_id, subject_id=payload.subject_id,
    ) if settings.enable_hermes_memory and profile.get("memoryEnabled", True) else []
    skill_instruction = "\n".join(
        f"可复用学习策略「{item['name']}」：{item['instructions']}" for item in active_skills
    )
    answer = await rag_service.answer_with_rag(
        user_id=user_id, subject_id=payload.subject_id, question=question,
        session_id=payload.session_id,
        teaching_instruction="\n".join(filter(None, [role["instruction"], skill_instruction])),
        allow_external_knowledge=(
            payload.allow_external_knowledge
            and get_subject(user_id=user_id, subject_id=payload.subject_id).get("externalKnowledgeEnabled", False)
        ),
        material_ids=payload.material_ids,
        block_types={
            "analyze_table": ["table"], "explain_chart": ["chart", "image"],
            "derive_formula": ["formula"],
        }.get(decision.primary_intent),
    )
    memory_updates = []
    if settings.enable_hermes_memory and profile.get("memoryEnabled", True):
        from app.worker.tasks import review_learning_interaction
        review_learning_interaction.delay(
            user_id, payload.subject_id, payload.session_id, question, answer["answer"], role_key,
        )
        memory_updates.append({"status": "queued", "type": "background_review"})
    return {
        "intent": decision.primary_intent, "intentConfidence": decision.confidence,
        "role": {"id": role_key, "name": role["name"]},
        "answer": answer["answer"], "citations": answer["citations"], "artifacts": [],
        "memoryUpdates": memory_updates, "suggestedActions": role["suggestions"],
        "traceId": trace_id, "messageId": answer["messageId"], "needsClarification": False,
    }
