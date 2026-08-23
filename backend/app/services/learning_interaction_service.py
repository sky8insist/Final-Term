from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.supabase_client import get_supabase_client


ACTIVE_STATUSES = ("awaiting_answer", "awaiting_clarification")
SELECT_FIELDS = (
    "id,user_id,subject_id,session_id,interaction_type,source_mode,status,question_id,"
    "attempt_id,parent_interaction_id,knowledge_key,question_text,expected_response_type,"
    "source_query,current_step,attempt_count,evidence,metadata,expires_at,created_at,updated_at"
)


def get_active_interaction(
    *, user_id: str, subject_id: str, session_id: str, interaction_id: str | None = None,
) -> dict | None:
    """Return a session-bound pending interaction, never a cross-session record."""
    try:
        query = (
            get_supabase_client().table("learning_interactions").select(SELECT_FIELDS)
            .eq("user_id", user_id).eq("subject_id", subject_id).eq("session_id", session_id)
        )
        if interaction_id:
            query = query.eq("id", interaction_id)
        else:
            query = query.in_("status", list(ACTIVE_STATUSES)).order("updated_at", desc=True)
        rows = query.limit(1).execute().data
        return rows[0] if rows else None
    except Exception:
        # The application remains deployable while migration 026 is rolling out.
        return None


def create_interaction(
    *, user_id: str, subject_id: str, session_id: str, question_text: str,
    source_mode: str, source_query: str, citations: list[dict],
    knowledge_key: str | None = None, question_id: str | None = None,
    attempt_id: str | None = None, metadata: dict | None = None,
) -> dict | None:
    evidence = {
        "citations": citations,
        "citationIds": [str(item.get("id")) for item in citations if item.get("id")],
    }
    payload = {
        "user_id": user_id, "subject_id": subject_id, "session_id": session_id,
        "interaction_type": "socratic" if source_mode == "socratic" else "practice",
        "source_mode": source_mode, "status": "awaiting_answer",
        "question_id": question_id, "attempt_id": attempt_id,
        "knowledge_key": knowledge_key, "question_text": question_text.strip(),
        "expected_response_type": "reasoning", "source_query": source_query.strip(),
        "evidence": evidence, "metadata": metadata or {},
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    }
    try:
        suspend_active_interactions(
            user_id=user_id, subject_id=subject_id, session_id=session_id,
        )
        rows = (
            get_supabase_client().table("learning_interactions").insert(payload)
            .select(SELECT_FIELDS).execute().data
        )
        return rows[0] if rows else None
    except Exception:
        return None


def update_interaction(
    *, user_id: str, interaction_id: str, changes: dict,
) -> dict | None:
    allowed = {
        "status", "question_text", "knowledge_key", "current_step", "attempt_count",
        "evidence", "metadata", "expires_at",
    }
    payload = {key: value for key, value in changes.items() if key in allowed}
    if not payload:
        return None
    try:
        rows = (
            get_supabase_client().table("learning_interactions").update(payload)
            .eq("id", interaction_id).eq("user_id", user_id)
            .select(SELECT_FIELDS).execute().data
        )
        return rows[0] if rows else None
    except Exception:
        return None


def suspend_active_interactions(*, user_id: str, subject_id: str, session_id: str) -> None:
    try:
        (
            get_supabase_client().table("learning_interactions")
            .update({"status": "suspended"}).eq("user_id", user_id)
            .eq("subject_id", subject_id).eq("session_id", session_id)
            .in_("status", list(ACTIVE_STATUSES)).execute()
        )
    except Exception:
        return

