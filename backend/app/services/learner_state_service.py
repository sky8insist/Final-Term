"""Canonical read projection; memory and browser caches are never state authority."""
from datetime import UTC, datetime

from app.db.supabase_client import get_supabase_client
from app.services.subject_service import get_subject

STATE_VERSION = "learner-state-v1"


def _time(value) -> datetime | None:
    if not value:
        return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=UTC)


def derive_state(row: dict | None, *, covered: bool = False, now: datetime | None = None) -> dict:
    row = row or {}
    now = now or datetime.now(UTC)
    meta = row.get("metadata") or {}
    evidence = meta.get("lastEvidence") or {}
    mastery = float(row.get("mastery", 0.5))
    data_confidence = float(row.get("confidence", 0))
    assessment_count = int(meta.get("assessmentCount", 0))
    assessment_streak = int(meta.get("assessmentCorrectStreak", 0))
    learner_confidence = meta.get("learnerConfidence", evidence.get("selfRating"))
    misconception = float(meta.get("misconceptionRisk", 0))
    due = _time(row.get("next_review_at"))
    has_practice = int(row.get("attempts", 0)) > 0
    sufficient = assessment_count >= 3 and assessment_streak >= 3 and data_confidence >= 0.5
    recall_risk = bool(meta.get("flashcardRecallRisk"))
    mastered = mastery >= 0.8 and sufficient and not recall_risk
    previously_mastered = bool(meta.get("masteredAt"))
    reasons = []
    if has_practice and ((due is not None and due <= now and (mastered or previously_mastered))
                         or (previously_mastered and not mastered) or misconception >= 0.75 or recall_risk):
        state = "at_risk"
        if due is not None and due <= now: reasons.append("复习已到期")
        if previously_mastered and not mastered: reasons.append("掌握证据下降")
        if misconception >= 0.75: reasons.append("高信心错误，需要纠正理解")
        if recall_risk: reasons.append("闪卡回忆失败，需要重新评估")
    elif mastered:
        state = "mastered"
    elif has_practice:
        state = "practicing"
    elif covered:
        state = "covered"
    else:
        state = "not_started"
    return {"state": state, "masteryScore": mastery, "masteryConfidence": data_confidence,
            "learnerConfidence": learner_confidence, "misconceptionRisk": misconception,
            "retentionRisk": 1.0 if due is not None and due <= now else 0.0,
            "assessmentCount": assessment_count, "assessmentEvidenceSufficient": sufficient,
            "nextReviewAt": row.get("next_review_at"), "reasons": reasons, "stateVersion": STATE_VERSION}


def list_states(*, user_id: str, subject_id: str) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    topics = (client.table("knowledge_points").select("id,title,knowledge_key,unit_id,archived")
              .eq("user_id", user_id).eq("subject_id", subject_id).order("sequence_index").execute().data)
    mastery = (client.table("knowledge_mastery").select("*").eq("user_id", user_id)
               .eq("subject_id", subject_id).execute().data)
    coverage = (client.table("topic_coverage").select("knowledge_point_id,covered_at").eq("user_id", user_id)
                .eq("subject_id", subject_id).execute().data)
    by_key = {row["knowledge_key"]: row for row in mastery}
    covered = {row["knowledge_point_id"]: row["covered_at"] for row in coverage}
    states = [{"knowledgePointId": topic["id"], "knowledgeKey": topic["knowledge_key"],
               "title": topic["title"], "unitId": topic["unit_id"], "coveredAt": covered.get(topic["id"]),
               **derive_state(by_key.get(topic["knowledge_key"]), covered=topic["id"] in covered)}
              for topic in topics if not topic["archived"]]
    return {"stateVersion": STATE_VERSION, "topics": states,
            "counts": {state: sum(row["state"] == state for row in states)
                       for state in ["not_started", "covered", "practicing", "mastered", "at_risk"]}}


def mark_covered(*, user_id: str, subject_id: str, topic_id: str) -> dict:
    from app.services.course_service import _owned
    _owned(table="knowledge_points", row_id=topic_id, user_id=user_id, subject_id=subject_id)
    # Duplicate writes keep the first coverage timestamp, never promote mastery.
    get_supabase_client().table("topic_coverage").upsert({
        "user_id": user_id, "subject_id": subject_id, "knowledge_point_id": topic_id,
    }, on_conflict="user_id,subject_id,knowledge_point_id", ignore_duplicates=True).execute()
    return {"knowledgePointId": topic_id, "covered": True}
