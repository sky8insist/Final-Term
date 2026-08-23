from __future__ import annotations

from app.db.supabase_client import get_supabase_client
from app.services.learning_interaction_service import get_active_interaction
from app.services.question_context_service import as_interaction, get_question_context


def _recent_messages(*, user_id: str, subject_id: str, session_id: str, limit: int = 8) -> list[dict]:
    try:
        rows = (
            get_supabase_client().table("chat_messages")
            .select("id,role,content,citations,metadata,created_at")
            .eq("user_id", user_id).eq("subject_id", subject_id).eq("session_id", session_id)
            .order("created_at", desc=True).limit(limit).execute().data
        )
    except Exception:
        try:
            rows = (
                get_supabase_client().table("chat_messages")
                .select("id,role,content,citations,created_at")
                .eq("user_id", user_id).eq("subject_id", subject_id).eq("session_id", session_id)
                .order("created_at", desc=True).limit(limit).execute().data
            )
        except Exception:
            return []
    return list(reversed(rows or []))


def resolve_conversation_context(
    *, user_id: str, subject_id: str, session_id: str,
    interaction_id: str | None = None,
    question_id: str | None = None, attempt_id: str | None = None, mode: str = "academic",
) -> dict:
    active = get_active_interaction(
        user_id=user_id, subject_id=subject_id, session_id=session_id,
        interaction_id=interaction_id,
    )
    question_context = None
    if not active and question_id:
        question_context = get_question_context(
            user_id=user_id, subject_id=subject_id, question_id=question_id, attempt_id=attempt_id,
        )
        if question_context:
            active = as_interaction(question_context, mode=mode, attempt_id=attempt_id)
    recent = _recent_messages(
        user_id=user_id, subject_id=subject_id, session_id=session_id,
    )
    last_assistant = next((item for item in reversed(recent) if item.get("role") == "assistant"), None)
    return {
        "activeInteraction": active,
        "recentTurns": recent,
        "hasPendingQuestion": bool(active and active.get("status") in {"awaiting_answer", "awaiting_clarification"}),
        "lastAssistantMessage": last_assistant,
        "knowledgePoint": active.get("knowledge_key") if active else None,
        "questionContext": question_context,
    }
