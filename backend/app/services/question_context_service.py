from __future__ import annotations

import json

from app.db.supabase_client import get_supabase_client
from app.services.llm_service import LLMServiceError, generate_text_async


def get_question_context(
    *, user_id: str, subject_id: str, question_id: str, attempt_id: str | None = None,
) -> dict | None:
    try:
        client = get_supabase_client()
        rows = (
            client.table("questions").select("id,subject_id,question_type,knowledge_key,current_version")
            .eq("id", question_id).eq("user_id", user_id).eq("subject_id", subject_id)
            .limit(1).execute().data
        )
        if not rows:
            return None
        question = rows[0]
        versions = (
            client.table("question_versions").select("stem,options,correct_answer,explanation,rubric,citations")
            .eq("question_id", question_id).eq("version", question["current_version"])
            .limit(1).execute().data
        )
        if not versions:
            return None
        version = versions[0]
        answers_visible = True
        if attempt_id:
            attempts = (
                client.table("exam_attempts").select("status")
                .eq("id", attempt_id).eq("user_id", user_id).eq("subject_id", subject_id)
                .limit(1).execute().data
            )
            answers_visible = bool(attempts and attempts[0].get("status") in {"submitted", "graded", "expired"})
        return {
            **question, "stem": version["stem"], "options": version.get("options") or [],
            "correctAnswer": version.get("correct_answer") if answers_visible else None,
            "explanation": version.get("explanation") if answers_visible else None,
            "rubric": version.get("rubric") if answers_visible else None,
            "citations": version.get("citations") or [], "answersVisible": answers_visible,
        }
    except Exception:
        return None


def as_interaction(question: dict, *, mode: str, attempt_id: str | None = None) -> dict:
    return {
        "id": f"question:{question['id']}", "status": "awaiting_answer",
        "interaction_type": "exam_review", "source_mode": mode,
        "question_id": question["id"], "attempt_id": attempt_id,
        "knowledge_key": question.get("knowledge_key"), "question_text": question["stem"],
        "attempt_count": 0, "current_step": 0,
        "evidence": {"citations": question.get("citations") or []},
        "metadata": {"questionContext": True, "answersVisible": question["answersVisible"],
                     "evaluation": {"correctAnswer": question.get("correctAnswer"),
                                    "rubric": question.get("rubric"),
                                    "explanation": question.get("explanation"),
                                    "options": question.get("options") or []}},
    }


async def explain_question(*, interaction: dict, user_message: str, mode: str) -> str:
    metadata = interaction.get("metadata") or {}
    if not metadata.get("answersVisible", False):
        return "这道题仍处于作答阶段，我不能提前透露答案或解析。你可以先提交答案，或说明你卡在哪一步。"
    evaluation = metadata.get("evaluation") or {}
    prompt = f"""你是复习题讲解助手。根据固定题目答案和解析回答学生问题。
不得改变标准答案或评分量规；课程证据不足时明确说明。使用中文，简洁清晰。
模式：{mode}
题目：{interaction.get('question_text', '')}
选项：{json.dumps(evaluation.get('options') or [], ensure_ascii=False)}
固定答案：{json.dumps(evaluation.get('correctAnswer'), ensure_ascii=False)}
固定解析：{evaluation.get('explanation') or ''}
评分量规：{json.dumps(evaluation.get('rubric'), ensure_ascii=False)}
学生问题：{user_message}"""
    try:
        return await generate_text_async(prompt, temperature=0)
    except LLMServiceError:
        return str(evaluation.get("explanation") or "当前无法生成进一步讲解，请稍后重试。")

