from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.supabase_client import get_supabase_client


ALGORITHM_VERSION = "study-signal-v1"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(float(value), low), high)


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _safe_rows(query) -> list[dict]:
    try:
        return list(query.execute().data or [])
    except Exception:
        # Signals are intentionally degradable while optional migrations roll out.
        return []


def calculate_need_score(signal: dict, *, now: datetime | None = None) -> tuple[float, dict[str, float]]:
    now = now or datetime.now(UTC)
    mastery = _clamp(signal.get("mastery", 0.5))
    attempts = max(int(signal.get("attemptCount", 0)), 0)
    correct = max(int(signal.get("correctCount", 0)), 0)
    score_ratio = _clamp(signal.get("scoreRatio", correct / attempts if attempts else 0.5))
    error_ratio = 1 - (correct / attempts if attempts else score_ratio)
    last_practiced = _datetime(signal.get("lastPracticedAt") or signal.get("lastReviewedAt"))
    days_since = max((now - last_practiced).days, 0) if last_practiced else 60
    forgetting = _clamp(days_since / 30)
    dialogue_events = max(int(signal.get("dialogueEventCount", 0)), 0)
    hint_requests = max(int(signal.get("hintRequestCount", 0)), 0)
    incomplete = max(int(signal.get("incompleteInteractionCount", 0)), 0)
    confusion = _clamp((dialogue_events + hint_requests * 1.5 + incomplete) / 6)
    importance = _clamp(signal.get("importance", 0.5))
    prerequisite = _clamp(signal.get("prerequisiteWeight", 0))
    evidence_count = attempts + dialogue_events + int(signal.get("masteryEvidenceCount", 0))
    data_confidence = _clamp(signal.get("confidence", 0) * 0.6 + min(evidence_count / 8, 1) * 0.4)
    components = {
        "masteryGap": round(1 - mastery, 4),
        "practiceLoss": round(_clamp(error_ratio * 0.7 + (1 - score_ratio) * 0.3), 4),
        "forgetting": round(forgetting, 4),
        "dialogueConfusion": round(confusion, 4),
        "importance": round(_clamp(importance * 0.8 + prerequisite * 0.2), 4),
        "dataConfidence": round(data_confidence, 4),
    }
    score = (
        components["masteryGap"] * 0.35
        + components["practiceLoss"] * 0.20
        + components["forgetting"] * 0.15
        + components["dialogueConfusion"] * 0.15
        + components["importance"] * 0.10
        + components["dataConfidence"] * 0.05
    )
    return round(_clamp(score), 4), components


def _reason_lines(signal: dict, components: dict[str, float]) -> list[str]:
    reasons: list[str] = []
    if int(signal.get("attemptCount", 0)):
        reasons.append(f"近期练习正确率 {round(float(signal.get('accuracy', 0)) * 100)}%")
    if components["masteryGap"] >= 0.4:
        reasons.append(f"当前掌握度 {round(float(signal.get('mastery', 0.5)) * 100)}%，仍有明显缺口")
    if int(signal.get("dialogueEventCount", 0)):
        reasons.append(f"AI 学习室中出现 {int(signal['dialogueEventCount'])} 次困惑或追问信号")
    if components["forgetting"] >= 0.5:
        reasons.append("距离上次有效练习时间较长，需要回忆巩固")
    if not reasons:
        reasons.append("依据课程知识点重要度安排基础覆盖")
    return reasons[:3]


def collect_study_signals(*, user_id: str, subject_id: str, observation_days: int = 60) -> dict:
    client = get_supabase_client()
    cutoff = datetime.now(UTC) - timedelta(days=min(max(observation_days, 30), 60))
    questions = _safe_rows(
        client.table("questions").select("id,knowledge_key,difficulty,created_at")
        .eq("user_id", user_id).eq("subject_id", subject_id)
    )
    question_by_id = {str(row["id"]): row for row in questions if row.get("id")}
    question_ids = list(question_by_id)
    grading: list[dict] = []
    if question_ids:
        grading = _safe_rows(
            client.table("grading_results")
            .select("question_id,attempt_id,earned_points,max_points,is_correct,feedback,error_type,created_at")
            .eq("user_id", user_id).in_("question_id", question_ids)
            .gte("created_at", cutoff.isoformat()).order("created_at")
        )
    mastery = _safe_rows(
        client.table("knowledge_mastery").select("knowledge_key,mastery,confidence,last_reviewed_at,next_review_at,metadata")
        .eq("user_id", user_id).eq("subject_id", subject_id)
    )
    history = _safe_rows(
        client.table("mastery_history").select("knowledge_key,correct,difficulty,evidence,created_at")
        .eq("user_id", user_id).eq("subject_id", subject_id)
        .gte("created_at", cutoff.isoformat()).order("created_at")
    )
    interactions = _safe_rows(
        client.table("learning_interactions")
        .select("knowledge_key,status,attempt_count,metadata,updated_at")
        .eq("user_id", user_id).eq("subject_id", subject_id)
        .gte("updated_at", cutoff.isoformat()).order("updated_at", desc=True).limit(300)
    )
    knowledge_points = _safe_rows(
        client.table("knowledge_points").select("knowledge_key,title,importance,prerequisites,metadata")
        .eq("user_id", user_id).eq("subject_id", subject_id)
    )
    chats = _safe_rows(
        client.table("chat_messages").select("content,metadata,created_at")
        .eq("user_id", user_id).eq("subject_id", subject_id).eq("role", "user")
        .gte("created_at", cutoff.isoformat()).order("created_at", desc=True).limit(120)
    )

    raw: dict[str, dict] = defaultdict(lambda: {
        "attemptCount": 0, "correctCount": 0, "earnedPoints": 0.0, "maxPoints": 0.0,
        "consecutiveCorrect": 0, "dialogueEventCount": 0, "hintRequestCount": 0,
        "incompleteInteractionCount": 0, "masteryEvidenceCount": 0,
        "subjectiveFeedback": [], "difficulties": [], "sources": set(),
    })
    for point in knowledge_points:
        key = str(point.get("knowledge_key") or "").strip()
        if not key:
            continue
        item = raw[key]
        item.update({
            "title": point.get("title") or key,
            "importance": _clamp(float(point.get("importance", 50)) / 100),
            "prerequisiteWeight": _clamp(len(point.get("prerequisites") or []) / 4),
        })
    for row in grading:
        question = question_by_id.get(str(row.get("question_id"))) or {}
        key = str(question.get("knowledge_key") or "").strip()
        if not key:
            continue
        item = raw[key]
        item["attemptCount"] += 1
        is_correct = bool(row.get("is_correct"))
        item["correctCount"] += int(is_correct)
        item["consecutiveCorrect"] = item["consecutiveCorrect"] + 1 if is_correct else 0
        item["earnedPoints"] += float(row.get("earned_points") or 0)
        item["maxPoints"] += float(row.get("max_points") or 0)
        item["lastPracticedAt"] = row.get("created_at") or item.get("lastPracticedAt")
        item["difficulties"].append(question.get("difficulty") or "medium")
        if row.get("feedback") and len(item["subjectiveFeedback"]) < 3:
            item["subjectiveFeedback"].append(str(row["feedback"])[:300])
        item["sources"].add("practice")
    for row in history:
        key = str(row.get("knowledge_key") or "").strip()
        if key:
            raw[key]["masteryEvidenceCount"] += 1
            raw[key]["lastReviewedAt"] = row.get("created_at") or raw[key].get("lastReviewedAt")
    for row in mastery:
        key = str(row.get("knowledge_key") or "").strip()
        if not key:
            continue
        raw[key].update({
            "mastery": _clamp(row.get("mastery", 0.5)),
            "confidence": _clamp(row.get("confidence", 0)),
            "lastPracticedAt": row.get("last_reviewed_at") or raw[key].get("lastPracticedAt"),
            "nextReviewAt": row.get("next_review_at"),
        })
    for row in interactions:
        key = str(row.get("knowledge_key") or "").strip()
        if not key:
            continue
        item = raw[key]
        metadata = row.get("metadata") or {}
        evaluation = metadata.get("lastEvaluation") or {}
        rating = str(evaluation.get("rating") or evaluation.get("result") or "").casefold()
        if rating not in {"correct", "pass", "fully_correct"}:
            item["dialogueEventCount"] += 1
        item["hintRequestCount"] += int(metadata.get("hintCount") or metadata.get("fullAnswerCount") or 0)
        if row.get("status") not in {"completed"}:
            item["incompleteInteractionCount"] += 1
        item["dialogueEventCount"] += min(int(row.get("attempt_count") or 0), 3)
        item["sources"].add("dialogue")
    known_keys = list(raw)
    for row in chats:
        metadata = row.get("metadata") or {}
        explicit = str(metadata.get("knowledgeKey") or metadata.get("knowledge_key") or "").strip()
        matches = [explicit] if explicit else [key for key in known_keys if key and key in str(row.get("content") or "")][:2]
        for key in matches:
            if key:
                raw[key]["dialogueEventCount"] += 1
                raw[key]["sources"].add("dialogue")

    if not raw:
        raw["课程核心知识"] = {
            "title": "课程核心知识", "importance": 0.8, "prerequisiteWeight": 0,
            "attemptCount": 0, "correctCount": 0, "earnedPoints": 0.0, "maxPoints": 0.0,
            "consecutiveCorrect": 0, "dialogueEventCount": 0, "hintRequestCount": 0,
            "incompleteInteractionCount": 0, "masteryEvidenceCount": 0,
            "subjectiveFeedback": [], "difficulties": [], "sources": set(),
        }
    signals = []
    for key, item in raw.items():
        attempts = int(item.get("attemptCount", 0))
        correct = int(item.get("correctCount", 0))
        item["knowledgeKey"] = key
        item["title"] = item.get("title") or key
        item["accuracy"] = correct / attempts if attempts else 0
        item["scoreRatio"] = item["earnedPoints"] / item["maxPoints"] if item.get("maxPoints") else item["accuracy"]
        item.setdefault("mastery", 0.5)
        item.setdefault("confidence", 0)
        item.setdefault("importance", 0.5)
        item.setdefault("prerequisiteWeight", 0)
        score, components = calculate_need_score(item)
        item["needScore"] = score
        item["needComponents"] = components
        item["reasons"] = _reason_lines(item, components)
        item["sourceSignals"] = sorted(item.pop("sources"))
        signals.append(item)
    signals.sort(key=lambda item: (-item["needScore"], item["knowledgeKey"]))
    practice_count = len(grading)
    structured_dialogue_count = len(interactions)
    warnings: list[str] = []
    if practice_count < 3:
        warnings.append("练习数据较少")
    if structured_dialogue_count < 2:
        warnings.append("AI 学习室互动数据较少")
    if practice_count < 3 and structured_dialogue_count < 2:
        warnings.append("当前练习和互动数据较少，计划主要依据课程知识点重要度生成；完成更多练习后可重新优化。")
    return {
        "algorithmVersion": ALGORITHM_VERSION,
        "observationDays": min(max(observation_days, 30), 60),
        "signals": signals,
        "stats": {
            "practiceResults": practice_count,
            "examAttempts": len({row.get("attempt_id") for row in grading if row.get("attempt_id")}),
            "dialogueInteractions": structured_dialogue_count,
            "recentUserMessages": len(chats),
            "knowledgePoints": len(signals),
        },
        "warnings": warnings,
        "dataSufficient": practice_count >= 3 or structured_dialogue_count >= 2,
    }
