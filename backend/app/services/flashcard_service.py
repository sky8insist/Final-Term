import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.mastery_service import calculate_mastery

ALGORITHM_VERSION = "card-scheduler-v1"
RATINGS = {"again", "hard", "good", "easy"}


def schedule(state: dict, rating: str, *, now: datetime | None = None) -> dict:
    if rating not in RATINGS: raise HTTPException(422, "无效的闪卡评价")
    now = now or datetime.now(UTC)
    stability = max(0.25, float(state.get("stability", 0.25)))
    first = not state.get("last_review")
    last = datetime.fromisoformat(state["last_review"].replace("Z", "+00:00")) if not first else now
    elapsed = max(0, (now - last).total_seconds() / 86400)
    retrievability = math.exp(math.log(0.9) * elapsed / stability)
    difficulty = float(state.get("difficulty", 5))
    delta = {"again": 1, "hard": 0.3, "good": -0.1, "easy": -0.5}[rating]
    difficulty = min(10, max(1, difficulty + delta))
    if rating == "again": interval, stability = 10 / 1440, max(0.25, stability * 0.35)
    elif rating == "hard": interval = stability = max(1, stability * 0.8)
    elif rating == "good": interval = stability = 1 if first else max(1, stability * (1.8 + (10 - difficulty) / 10))
    else: interval = stability = 4 if first else max(4, stability * (2.7 + (10 - difficulty) / 10))
    stability = min(365, stability); interval = min(365, interval)
    return {"difficulty": round(difficulty, 4), "stability": round(stability, 4),
            "nextReview": (now + timedelta(days=interval)).isoformat(), "reviewedAt": now.isoformat(),
            "retrievabilityBefore": round(retrievability, 4), "algorithmVersion": ALGORITHM_VERSION}


def _card(user_id: str, artifact_id: str, card_id: str) -> dict:
    rows = (get_supabase_client().table("flashcards").select("*").eq("user_id", user_id)
            .eq("artifact_id", artifact_id).eq("card_id", card_id).eq("archived", False).limit(1).execute().data)
    if not rows: raise HTTPException(404, "闪卡不存在或已移除")
    return rows[0]


def review(*, user_id: str, artifact_id: str, card_id: str, rating: str,
           response_seconds: float | None = None, request_id: str | None = None, version: int | None = None) -> dict:
    if rating not in RATINGS: raise HTTPException(422, "无效的闪卡评价")
    client = get_supabase_client()
    request_id = request_id or str(uuid4())
    # Replay is returned before computing a new proposal, even after the card changed.
    logs = client.table("flashcard_review_logs").select("*").eq("user_id", user_id).eq("id", request_id).limit(1).execute().data
    if logs:
        log = logs[0]
        if log["artifact_id"] != artifact_id or log["card_id"] != card_id or log["rating"] != rating or (version is not None and log["expected_version"] != version):
            raise HTTPException(409, "请求编号已用于其他评价")
        return log["result"]
    card = _card(user_id, artifact_id, card_id)
    from app.services.course_service import resolve_topic, _owned
    topic = (_owned(table="knowledge_points", row_id=card["knowledge_point_id"], user_id=user_id, subject_id=card["subject_id"])
             if card["knowledge_point_id"] else resolve_topic(client=client, user_id=user_id, subject_id=card["subject_id"],
                 title=str(card.get("knowledge_key") or card["front"])[:300]))
    if topic.get("archived"): raise HTTPException(409, "请先恢复知识点后再复习")
    states = client.table("flashcard_review_state").select("*").eq("user_id", user_id).eq("artifact_id", artifact_id).eq("card_id", card_id).limit(1).execute().data
    state = states[0]
    if version is not None and version != state["version"]: raise HTTPException(409, "闪卡已更新，请刷新后继续")
    mastery_rows = (client.table("knowledge_mastery").select("*").eq("user_id", user_id).eq("subject_id", card["subject_id"])
                    .eq("knowledge_key", topic["knowledge_key"]).limit(1).execute().data)
    current = mastery_rows[0] if mastery_rows else {"mastery": 0.5, "confidence": 0, "attempts": 0, "correct_attempts": 0, "metadata": {}}
    now = datetime.now(UTC); proposal = schedule(state, rating, now=now)
    correct = rating in {"good", "easy"}
    score, _, evidence = calculate_mastery(previous=current["mastery"], attempts=current["attempts"], correct=correct,
        difficulty="medium", hints=int(rating == "hard"), response_seconds=response_seconds,
        self_rating={"again": 0.1, "hard": 0.5, "good": 0.9, "easy": 1}[rating])
    metadata = {**(current.get("metadata") or {})}
    if rating == "again" and metadata.get("masteredAt"):
        metadata.update(flashcardRecallRisk=True, assessmentCorrectStreak=0)
    evidence.update(evidenceType="flashcard", algorithmVersion=ALGORITHM_VERSION, knowledgePointId=topic["id"],
                    rating=rating, retrievabilityBefore=proposal["retrievabilityBefore"])
    from app.services.learner_state_service import derive_state
    next_review = now.isoformat() if rating == "again" else proposal["nextReview"]
    mastery = {"knowledge_key": topic["knowledge_key"], "mastery": score, "confidence": current["confidence"],
        "attempts": current["attempts"] + 1, "correct_attempts": current["correct_attempts"] + int(correct),
        "last_reviewed_at": now.isoformat(), "next_review_at": next_review,
        "metadata": {**metadata, "lastEvidence": evidence, "lastFlashcardReviewId": request_id}}
    evidence.update(stateBefore=derive_state(current, now=now)["state"], stateAfter=derive_state(mastery, now=now)["state"])
    try:
        return client.rpc("commit_flashcard_review", {"p_user_id": user_id, "p_artifact_id": artifact_id, "p_card_id": card_id,
            "p_request_id": request_id, "p_expected_version": state["version"], "p_rating": rating,
            "p_values": {**proposal, "mastery": mastery, "masteryUpdatedAt": current.get("updated_at"),
                         "evidence": evidence, "topicId": topic["id"], "responseSeconds": response_seconds}}).execute().data
    except Exception as exc:
        if getattr(exc, "code", None) in {"40001", "40P01"}: raise HTTPException(409, "闪卡或掌握度已更新，请刷新后重试") from exc
        if getattr(exc, "code", None) == "42501": raise HTTPException(404, "闪卡不存在") from exc
        raise


def queue(*, user_id: str, subject_id: str | None = None, artifact_id: str | None = None,
          include_future: bool = False, limit: int = 50) -> dict:
    if subject_id:
        from app.services.subject_service import get_subject
        get_subject(user_id=user_id, subject_id=subject_id)
    if artifact_id:
        from app.services.artifact_service import get_artifact
        artifact = get_artifact(user_id=user_id, artifact_id=artifact_id)
        if artifact["artifact_type"] != "flashcards":
            raise HTTPException(409, "Artifact is not a flashcard deck")
    return get_supabase_client().rpc("flashcard_queue", {
        "p_user_id": user_id, "p_subject_id": subject_id, "p_artifact_id": artifact_id,
        "p_include_future": include_future, "p_limit": min(max(limit, 1), 200),
    }).execute().data


def history(*, user_id: str, artifact_id: str, card_id: str) -> list[dict]:
    _card(user_id, artifact_id, card_id)
    return (get_supabase_client().table("flashcard_review_logs").select("id,rating,reviewed_at,state_before,state_after,content_version,response_seconds")
            .eq("user_id", user_id).eq("artifact_id", artifact_id).eq("card_id", card_id).order("reviewed_at", desc=True).limit(50).execute().data)
