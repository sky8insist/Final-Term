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
    if self_rating is not None:
        performance = performance * 0.8 + min(max(self_rating, 0), 1) * 0.2
    performance = min(max(performance, 0), 1)
    # Bayesian-style smoothing: early observations cannot collapse mastery.
    learning_rate = min(0.15 + attempts * 0.03, 0.35)
    next_mastery = previous * (1 - learning_rate) + performance * learning_rate
    confidence = min((attempts + 1) / 6, 1)
    return round(next_mastery, 4), round(confidence, 4), {
        "performance": performance, "difficultyWeight": difficulty_weight,
        "hints": hints, "responseSeconds": response_seconds, "selfRating": self_rating,
    }


def record_performance(*, user_id: str, subject_id: str, knowledge_key: str,
                       correct: bool, difficulty: str, hints: int = 0,
                       response_seconds: float | None = None,
                       self_rating: float | None = None) -> dict:
    client = get_supabase_client()
    rows = client.table("knowledge_mastery").select("*").eq("user_id", user_id).eq("subject_id", subject_id).eq("knowledge_key", knowledge_key).limit(1).execute().data
    current = rows[0] if rows else {"mastery": 0.5, "attempts": 0, "correct_attempts": 0, "metadata": {}}
    mastery, confidence, evidence = calculate_mastery(
        previous=float(current["mastery"]), attempts=int(current["attempts"]), correct=correct,
        difficulty=difficulty, hints=hints, response_seconds=response_seconds, self_rating=self_rating,
    )
    streak = int(current.get("metadata", {}).get("correctStreak", 0)) + 1 if correct else 0
    interval_days = [1, 3, 7, 14, 30][min(streak, 5) - 1] if streak else 1
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id, "subject_id": subject_id, "knowledge_key": knowledge_key,
        "mastery": mastery, "confidence": confidence, "attempts": int(current["attempts"]) + 1,
        "correct_attempts": int(current["correct_attempts"]) + (1 if correct else 0),
        "last_reviewed_at": now.isoformat(), "next_review_at": (now + timedelta(days=interval_days)).isoformat(),
        "metadata": {**current.get("metadata", {}), "correctStreak": streak, "lastEvidence": evidence,
                     "intervalDays": interval_days},
    }
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
