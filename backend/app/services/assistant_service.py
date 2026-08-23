from uuid import uuid4

from app.agents.router_agent import route_intent
from app.config.settings import settings
from app.models.assistant import AssistantMessageRequest
from app.services import hermes_memory_service, rag_service
from app.services import memory_service
from app.services import artifact_service, exam_service, mastery_service, study_plan_service
from app.mindmap import service as mindmap_service
from app.models.exam import ExamGenerateRequest, QuestionTypeSpec
import re
from app.services.role_service import recommend_role
from app.services.subject_service import get_subject
from app.services.answer_evaluation_service import build_hint, evaluate_student_answer
from app.services.conversation_context_service import resolve_conversation_context
from app.services.dialogue_act_service import build_contextual_query, classify_dialogue_act
from app.services.learning_interaction_service import (
    create_interaction, suspend_active_interactions, update_interaction,
)
from app.services.question_context_service import explain_question


def _dialogue_payload(decision) -> dict:
    return decision.model_dump(by_alias=True)


def _pending_question_from_answer(answer: str) -> str | None:
    paragraphs = [item.strip() for item in re.split(r"\n+", answer) if item.strip()]
    for paragraph in reversed(paragraphs):
        if "？" in paragraph or "?" in paragraph:
            return paragraph[-1000:]
    return None


async def handle_message(*, user_id: str, payload: AssistantMessageRequest) -> dict:
    context = resolve_conversation_context(
        user_id=user_id, subject_id=payload.subject_id, session_id=payload.session_id,
        interaction_id=payload.interaction_id,
        question_id=payload.question_id, attempt_id=payload.attempt_id, mode=payload.role,
    )
    dialogue = await classify_dialogue_act(
        message=payload.message.strip(), context=context, mode=payload.role,
        override=payload.dialogue_act_override,
    )
    active_interaction = context.get("activeInteraction")
    if dialogue.dialogue_act in {
        "answer_to_pending_question", "request_hint", "request_full_solution",
    } and active_interaction:
        from app.models.assistant import IntentDecision
        decision = IntentDecision(
            primary_intent="qa", confidence=dialogue.confidence, needs_retrieval=False,
            needs_clarification=False, required_skills=["answer_evaluation"],
        )
    else:
        decision = await route_intent(payload.message.strip())
    profile = hermes_memory_service.get_profile(user_id=user_id)
    role_key, role = recommend_role(requested=payload.role, profile=profile, intent=decision.primary_intent)
    trace_id = str(uuid4())
    if dialogue.dialogue_act == "ambiguous":
        clarification = "你是在回答上一题，还是想提出一个新问题？"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=clarification, citations=[], session_id=payload.session_id,
            assistant_metadata={"dialogueAct": "ambiguous", "expectsReply": True},
        )
        return {
            "intent": "qa", "intentConfidence": dialogue.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": clarification,
            "citations": [], "artifacts": [], "memoryUpdates": [],
            "suggestedActions": ["回答上一题", "提出新问题"], "traceId": trace_id,
            "needsClarification": True, "messageId": message["id"],
            "dialogue": _dialogue_payload(dialogue),
            "interaction": {"id": active_interaction.get("id"), "status": "awaiting_clarification",
                            "expectsReply": True} if active_interaction else None,
        }

    if active_interaction and dialogue.dialogue_act == "answer_to_pending_question":
        evaluation = await evaluate_student_answer(
            interaction=active_interaction, student_answer=payload.message, mode=role_key,
        )
        next_question = evaluation.get("nextQuestion")
        next_status = "completed" if evaluation["nextAction"] == "complete" else "awaiting_answer"
        next_metadata = {**(active_interaction.get("metadata") or {}), "lastEvaluation": evaluation}
        updated = update_interaction(
            user_id=user_id, interaction_id=str(active_interaction["id"]), changes={
                "status": next_status,
                "question_text": next_question or active_interaction["question_text"],
                "attempt_count": int(active_interaction.get("attempt_count") or 0) + 1,
                "current_step": int(active_interaction.get("current_step") or 0) + (1 if next_question else 0),
                "metadata": next_metadata,
            },
        ) or {**active_interaction, "status": next_status, "question_text": next_question or active_interaction["question_text"]}
        citations = (active_interaction.get("evidence") or {}).get("citations") or []
        external_used = any(item.get("sourceType") == "external" for item in citations)
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=evaluation["answer"], citations=citations, session_id=payload.session_id,
            user_metadata={"dialogueAct": "answer_to_pending_question", "interactionId": active_interaction["id"]},
            assistant_metadata={"interactionId": active_interaction["id"], "expectsReply": next_status == "awaiting_answer"},
        )
        return {
            "intent": "qa", "intentConfidence": dialogue.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": evaluation["answer"],
            "citations": citations, "artifacts": [], "memoryUpdates": [],
            "suggestedActions": role["suggestions"], "traceId": trace_id,
            "messageId": message["id"], "needsClarification": False,
            "dialogue": _dialogue_payload(dialogue), "evaluation": evaluation,
            "interaction": {"id": updated.get("id"), "status": next_status,
                            "expectsReply": next_status == "awaiting_answer"},
            "generation": {"provider": settings.model_provider, "model": settings.llm_model,
                           "mocked": False,
                           "grounded": bool(citations) and not external_used,
                           "citationCount": len(citations), "retrievalSources": ["interaction"],
                           "externalUsed": external_used},
        }

    if active_interaction and dialogue.dialogue_act in {"request_hint", "request_full_solution"}:
        if (active_interaction.get("metadata") or {}).get("questionContext"):
            hint = await explain_question(
                interaction=active_interaction, user_message=payload.message, mode=role_key,
            )
        else:
            hint = build_hint(active_interaction)
            if dialogue.dialogue_act == "request_full_solution" and role_key != "socratic":
                hint = "我会先依据原题和课程资料展开解析。" + "\n\n" + hint
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=hint, citations=(active_interaction.get("evidence") or {}).get("citations") or [],
            session_id=payload.session_id,
            assistant_metadata={"interactionId": active_interaction["id"], "expectsReply": True},
        )
        return {
            "intent": "qa", "intentConfidence": dialogue.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": hint,
            "citations": (active_interaction.get("evidence") or {}).get("citations") or [],
            "artifacts": [], "memoryUpdates": [], "suggestedActions": role["suggestions"],
            "traceId": trace_id, "messageId": message["id"], "needsClarification": False,
            "dialogue": _dialogue_payload(dialogue),
            "interaction": {"id": active_interaction["id"], "status": "awaiting_answer", "expectsReply": True},
        }

    if (
        active_interaction
        and (active_interaction.get("metadata") or {}).get("questionContext")
        and dialogue.dialogue_act in {"followup_question_same_topic", "challenge_or_correction"}
    ):
        explanation = await explain_question(
            interaction=active_interaction, user_message=payload.message, mode=role_key,
        )
        citations = (active_interaction.get("evidence") or {}).get("citations") or []
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=explanation, citations=citations, session_id=payload.session_id,
            assistant_metadata={"questionId": payload.question_id, "expectsReply": True},
        )
        return {
            "intent": "qa", "intentConfidence": dialogue.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": explanation,
            "citations": citations, "artifacts": [], "memoryUpdates": [],
            "suggestedActions": role["suggestions"], "traceId": trace_id,
            "messageId": message["id"], "needsClarification": False,
            "dialogue": _dialogue_payload(dialogue),
            "interaction": {"id": active_interaction["id"], "status": "awaiting_answer", "expectsReply": True},
        }
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
        if decision.primary_intent == "generate_mind_map":
            artifact = await mindmap_service.generate_mind_map(
                user_id=user_id, subject_id=payload.subject_id,
                mode="question", query=payload.message, topic_id=None, chapter_id=None,
                max_depth=3, include_mastery=True,
                material_ids=payload.material_ids, count=24,
            )
        else:
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
                QuestionTypeSpec(questionType="fill_blank", count=2, pointsEach=5),
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
                QuestionTypeSpec(questionType="fill_blank", count=2, pointsEach=5),
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

    if decision.primary_intent == "analyze_practice_performance":
        from app.services import study_signal_service
        signal_result = study_signal_service.collect_study_signals(
            user_id=user_id, subject_id=payload.subject_id,
        )
        weakest = signal_result["signals"][:5]
        if signal_result["dataSufficient"]:
            overview = "；".join(
                f"{item['knowledgeKey']}（掌握度 {round(float(item.get('mastery', 0.5)) * 100)}%，优先级 {round(float(item['needScore']) * 100)}）"
                for item in weakest
            )
            answer_text = f"根据近期练习和 AI 学习室互动，当前优先关注：{overview}。"
        else:
            answer_text = "当前练习和互动数据较少，暂时只能依据课程知识点重要度给出薄弱点概览；完成更多练习后可重新分析。"
        message = memory_service.record_qa_history(
            user_id=user_id, subject_id=payload.subject_id, question=payload.message,
            answer=answer_text, citations=[],
            session_id=payload.session_id,
        )
        return {
            "intent": decision.primary_intent, "intentConfidence": decision.confidence,
            "role": {"id": role_key, "name": role["name"]}, "answer": answer_text,
            "citations": [], "artifacts": [], "memoryUpdates": [],
            "suggestedActions": ["生成专项练习", "生成复习计划"],
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
    if dialogue.dialogue_act == "new_question" and active_interaction:
        suspend_active_interactions(
            user_id=user_id, subject_id=payload.subject_id, session_id=payload.session_id,
        )
    question = payload.message
    if dialogue.dialogue_act in {"followup_question_same_topic", "challenge_or_correction"}:
        question = build_contextual_query(payload.message, dialogue, context)
    active_skills = hermes_memory_service.list_active_skills(
        user_id=user_id, subject_id=payload.subject_id,
    ) if settings.enable_hermes_memory and profile.get("memoryEnabled", True) else []
    skill_instruction = "\n".join(
        f"可复用学习策略「{item['name']}」：{item['instructions']}" for item in active_skills
    )
    answer = await rag_service.answer_with_rag(
        user_id=user_id, subject_id=payload.subject_id, question=question,
        history_question=payload.message,
        session_id=payload.session_id,
        teaching_instruction="\n".join(filter(None, [role["instruction"], skill_instruction])),
        allow_external_knowledge=(
            (payload.allow_external_knowledge or payload.knowledge_policy != "course_only")
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
    interaction = None
    if role_key == "socratic":
        pending_question = _pending_question_from_answer(answer["answer"])
        if pending_question:
            interaction = create_interaction(
                user_id=user_id, subject_id=payload.subject_id, session_id=payload.session_id,
                question_text=pending_question, source_mode=role_key, source_query=question,
                citations=answer["citations"], question_id=payload.question_id,
                attempt_id=payload.attempt_id,
                metadata={"originMessage": payload.message, "knowledgePolicy": payload.knowledge_policy},
            )
    return {
        "intent": decision.primary_intent, "intentConfidence": decision.confidence,
        "role": {"id": role_key, "name": role["name"]},
        "answer": answer["answer"], "citations": answer["citations"], "artifacts": [],
        "generation": answer.get("generation"),
        "memoryUpdates": memory_updates, "suggestedActions": role["suggestions"],
        "traceId": trace_id, "messageId": answer["messageId"], "needsClarification": False,
        "dialogue": _dialogue_payload(dialogue),
        "interaction": ({"id": interaction.get("id"), "status": interaction.get("status"),
                         "expectsReply": True} if interaction else None),
    }
