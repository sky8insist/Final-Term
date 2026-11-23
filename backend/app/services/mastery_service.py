from datetime import UTC, datetime, timedelta

from app.db.supabase_client import get_supabase_client

DIFFICULTY_WEIGHT = {"easy": 0.8, "medium": 1.0, "hard": 1.2}


def calculate_mastery(*, previous: float, attempts: int, correct: bool, difficulty: str,
                      hints: int = 0, response_seconds: float | None = None,
                      self_rating: float | None = None) -> tuple[float, float, dict]:
    difficulty_weight = DIFFICULTY_WEIGHT.get(difficulty, 1.0)
    performance = (1.0 if correct else 0.0) * difficulty_weight
    performance -= min(max(hints, 0) * 0.08, 0.32)
    if response_seconds is not None and response_seconds > 600:
        performance -= 0.05
    # Subjective confidence diagnoses calibration; it cannot turn an error into evidence of mastery.
    performance = min(max(performance, 0), 1)
    # Bayesian-style smoothing: early observations cannot collapse mastery.
    learning_rate = min(0.15 + attempts * 0.03, 0.35)
    next_mastery = previous * (1 - learning_rate) + performance * learning_rate
    confidence = min((attempts + 1) / 6, 1)
    return round(next_mastery, 4), round(confidence, 4), {
        "performance": performance, "difficultyWeight": difficulty_weight,
        "hints": hints, "responseSeconds": response_seconds, "selfRating": self_rating,
        "algorithmVersion": "mastery-v2",
    }


def record_performance(*, user_id: str, subject_id: str, knowledge_key: str,
                       correct: bool, difficulty: str, hints: int = 0,
                       response_seconds: float | None = None,
                       self_rating: float | None = None, evidence_type: str = "assessment") -> dict:
    client = get_supabase_client()
    from app.services.course_service import resolve_topic
    from app.services.learner_state_service import derive_state
    topic = resolve_topic(client=client, user_id=user_id, subject_id=subject_id, title=knowledge_key)
    knowledge_key = topic["knowledge_key"]
    rows = client.table("knowledge_mastery").select("*").eq("user_id", user_id).eq("subject_id", subject_id).eq("knowledge_key", knowledge_key).limit(1).execute().data
    current = rows[0] if rows else {"mastery": 0.5, "attempts": 0, "correct_attempts": 0, "metadata": {}}
    mastery, confidence, evidence = calculate_mastery(
        previous=float(current["mastery"]), attempts=int(current["attempts"]), correct=correct,
        difficulty=difficulty, hints=hints, response_seconds=response_seconds, self_rating=self_rating,
    )
    streak = int(current.get("metadata", {}).get("correctStreak", 0)) + 1 if correct else 0
    interval_days = [1, 3, 7, 14, 30][min(streak, 5) - 1] if streak else 1
    now = datetime.now(UTC)
    metadata = current.get("metadata") or {}
    assessment_count = int(metadata.get("assessmentCount", 0)) + int(evidence_type == "assessment")
    assessment_streak = int(metadata.get("assessmentCorrectStreak", 0))
    if evidence_type == "assessment":
        assessment_streak = assessment_streak + 1 if correct else 0
    recall_risk = bool(metadata.get("flashcardRecallRisk"))
    if evidence_type == "assessment" and assessment_streak >= 3:
        recall_risk = False
    evidence.update({"evidenceType": evidence_type,
                     "confidenceMismatch": abs(float(self_rating) - int(correct)) if self_rating is not None else None})
    misconception = float(metadata.get("misconceptionRisk", 0))
    if evidence_type == "assessment":
        misconception = float(self_rating) if not correct and self_rating is not None else misconception * 0.5
    payload = {
        "user_id": user_id, "subject_id": subject_id, "knowledge_key": knowledge_key,
        "mastery": mastery, "confidence": confidence, "attempts": int(current["attempts"]) + 1,
        "correct_attempts": int(current["correct_attempts"]) + (1 if correct else 0),
        "last_reviewed_at": now.isoformat(), "next_review_at": (now + timedelta(days=interval_days)).isoformat(),
        "metadata": {**current.get("metadata", {}), "correctStreak": streak, "lastEvidence": evidence,
                     "intervalDays": interval_days, "assessmentCount": assessment_count,
                     "assessmentCorrectStreak": assessment_streak, "misconceptionRisk": misconception,
                     "flashcardRecallRisk": recall_risk,
                     "learnerConfidence": self_rating if self_rating is not None else metadata.get("learnerConfidence")},
    }
    coverage = (client.table("topic_coverage").select("knowledge_point_id").eq("user_id", user_id)
                .eq("subject_id", subject_id).eq("knowledge_point_id", topic["id"]).limit(1).execute().data)
    before, after = derive_state(current, covered=bool(coverage), now=now), derive_state(payload, now=now)
    evidence.update({"stateBefore": before["state"], "stateAfter": after["state"],
                     "stateVersion": after["stateVersion"], "knowledgePointId": topic["id"]})
    if after["state"] == "mastered":
        payload["metadata"].setdefault("masteredAt", now.isoformat())
    saved = client.table("knowledge_mastery").upsert(
        payload, on_conflict="user_id,subject_id,knowledge_key",
    ).select("*").execute().data[0]
    client.table("mastery_history").insert({
        "user_id": user_id, "subject_id": subject_id, "knowledge_key": knowledge_key,
        "mastery": mastery, "confidence": confidence, "correct": correct,
        "difficulty": difficulty, "evidence": evidence,
    }).execute()
    return saved


def list_mastery(*, user_id: str, subject_id: str) -> list[dict]:
    return get_supabase_client().table("knowledge_mastery").select("*").eq("user_id", user_id).eq("subject_id", subject_id).order("mastery").execute().data


def mastery_trends(*, user_id: str, subject_id: str, limit: int = 200) -> list[dict]:
    return (
        get_supabase_client().table("mastery_history").select("*")
        .eq("user_id", user_id).eq("subject_id", subject_id)
        .order("created_at", desc=False).limit(min(max(limit, 1), 1000)).execute().data
    )
