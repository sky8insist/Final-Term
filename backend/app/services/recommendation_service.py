from datetime import UTC, date, datetime, timedelta, timezone
from urllib.parse import urlencode

from app.db.supabase_client import get_supabase_client
from app.services.learner_state_service import derive_state
from app.services.study_signal_service import calculate_need_score
from app.services.subject_service import get_subject

ALGORITHM_VERSION = "next-action-v2"


def build_recommendations(*, subjects: list[dict], topics: list[dict], mastery: list[dict],
                          coverage: list[dict], events: list[dict], mappings: list[dict],
                          tasks: list[dict], now: datetime | None = None, limit: int = 3) -> dict:
    now = now or datetime.now(UTC)
    today = now.astimezone(timezone(timedelta(hours=8))).date()
    subject_map = {row["id"]: row for row in subjects}
    mastery_map = {(row["subject_id"], row["knowledge_key"]): row for row in mastery}
    covered = {row["knowledge_point_id"] for row in coverage}
    active_topics = [row for row in topics if not row.get("archived") and row["subject_id"] in subject_map]
    upcoming = [row for row in events if row.get("status") == "active" and date.fromisoformat(row["exam_date"]) >= today
                and row["subject_id"] in subject_map]
    upcoming.sort(key=lambda row: (row["exam_date"], row["id"]))
    event_map = {row["id"]: row for row in upcoming}
    topic_map = {row["id"]: row for row in active_topics}
    # Ignore stale or inconsistent mappings before normalizing exam weights.
    mappings = [row for row in mappings
                if row["exam_event_id"] in event_map and row["knowledge_point_id"] in topic_map
                and event_map[row["exam_event_id"]]["subject_id"] == topic_map[row["knowledge_point_id"]]["subject_id"]]
    max_weight = {}
    for mapping in mappings:
        key = mapping["exam_event_id"]
        max_weight[key] = max(max_weight.get(key, 0), float(mapping["weight"]))
    topic_exams = {}
    for mapping in mappings:
        event = event_map.get(mapping["exam_event_id"])
        if event and float(mapping["weight"]) > 0:
            days = (date.fromisoformat(event["exam_date"]) - today).days
            urgency = max(0, 1 - days / 14) * float(mapping["weight"]) / max_weight[event["id"]]
            topic_exams.setdefault(mapping["knowledge_point_id"], []).append((urgency, days, event))

    actions, due_count, evidence_count = [], 0, 0
    weak_topics = []
    for topic in active_topics:
        row = mastery_map.get((topic["subject_id"], topic["knowledge_key"])) or {}
        state = derive_state(row, covered=topic["id"] in covered, now=now)
        meta = row.get("metadata") or {}
        evidence_count += state["assessmentCount"]
        due = bool(state["retentionRisk"])
        due_count += int(due)
        if state["masteryScore"] < 0.6 and int(row.get("attempts", 0)):
            weak_topics.append({"knowledgePointId": topic["id"], "title": topic["title"],
                                "subjectId": topic["subject_id"], "masteryScore": state["masteryScore"]})
        if state["state"] == "mastered" and not due:
            continue
        mismatch = float((meta.get("lastEvidence") or {}).get("confidenceMismatch") or 0)
        signal = {"mastery": state["masteryScore"], "confidence": state["masteryConfidence"],
                  "attemptCount": int(row.get("attempts", 0)), "correctCount": int(row.get("correct_attempts", 0)),
                  "importance": float(topic.get("importance", 50)) / 100,
                  "lastReviewedAt": row.get("last_reviewed_at"), "confidenceMismatch": mismatch}
        need, components = calculate_need_score(signal, now=now)
        matches = sorted(topic_exams.get(topic["id"], []), key=lambda item: (-item[0], item[1], item[2]["id"]))
        urgency, days, event = matches[0] if matches else (0, None, None)
        score = need * (1 + 0.8 * urgency) + 0.2 * int(due) + 0.1 * state["misconceptionRisk"]
        cold = state["assessmentCount"] < 3
        reasons = []
        if event:
            reasons.append(f"{event['title']}：{'今天考试' if days == 0 else str(days) + ' 天后考试'}，本知识点在考试范围内")
        if due: reasons.append("复习已到期")
        if state["misconceptionRisk"] >= 0.75: reasons.append("近期高信心答错，建议纠正概念理解")
        if meta.get("flashcardRecallRisk"): reasons.append("闪卡回忆失败，需要重新评估")
        if cold: reasons.append("评估证据不足，先建立学习与诊断基线")
        else: reasons.append(f"当前掌握度 {round(state['masteryScore'] * 100)}%")
        learn = state["state"] == "not_started" or state["misconceptionRisk"] >= 0.75
        actions.append({"id": topic["id"], "knowledgePointId": topic["id"], "subjectId": topic["subject_id"],
            "subjectName": subject_map[topic["subject_id"]]["name"], "topicTitle": topic["title"],
            "title": f"{'学习' if learn else '复习'} {topic['title']}", "actionType": "tutor" if learn else "practice",
            "state": state["state"], "masteryScore": state["masteryScore"], "estimatedMinutes": 25 if learn else 15,
            "priorityScore": round(score, 4), "reasons": reasons, "coldStart": cold,
            "href": "/guided-study?" + urlencode({"topicId": topic["id"], **({"examEventId": event["id"]} if event else {})}),
            "inputSignals": {**signal, "assessmentCount": state["assessmentCount"],
                             "misconceptionRisk": state["misconceptionRisk"], "dueReview": due,
                             "examEventId": event["id"] if event else None, "examUrgency": urgency,
                             "flashcardRecallRisk": bool(meta.get("flashcardRecallRisk")),
                             "covered": topic["id"] in covered},
            "scoreComponents": {**components, "examUrgency": round(urgency, 4), "dueReview": int(due)}})
    for subject_id, subject in subject_map.items():
        if not any(topic["subject_id"] == subject_id for topic in active_topics):
            actions.append({"id": f"setup:{subject_id}", "knowledgePointId": None, "subjectId": subject_id,
                "subjectName": subject["name"], "topicTitle": None, "title": f"建立 {subject['name']} 的课程目录",
                "actionType": "setup", "state": "not_started", "masteryScore": None, "estimatedMinutes": 10,
                "priorityScore": 0.3, "reasons": ["尚无课程知识点，请上传资料或添加课程结构"],
                "coldStart": True, "href": "/course", "inputSignals": {"activeTopicCount": 0}, "scoreComponents": {}})
    actions.sort(key=lambda item: (-item["priorityScore"], item["subjectId"], item["id"]))
    weak_topics.sort(key=lambda item: (item["masteryScore"], item["knowledgePointId"]))
    today_tasks = [{"id": row["id"], "subjectId": row["subject_id"], "title": row["title"],
                    "estimatedMinutes": row["estimated_minutes"]} for row in tasks
                   if row["subject_id"] in subject_map and row["status"] in {"pending", "overdue"}
                   and date.fromisoformat(row["scheduled_date"]) <= today]
    today_tasks.sort(key=lambda row: (row["subjectId"], row["id"]))
    return {"algorithmVersion": ALGORITHM_VERSION, "generatedAt": now.isoformat(),
            "actions": actions[:limit], "dueReviewCount": due_count, "weakTopics": weak_topics[:5],
            "upcomingExams": [{"id": row["id"], "title": row["title"], "examDate": row["exam_date"],
                               "subjectId": row["subject_id"], "subjectName": subject_map[row["subject_id"]]["name"]}
                              for row in upcoming[:3]], "todayTasks": today_tasks[:10],
            "coldStart": evidence_count < 3}


def next_actions(*, user_id: str, subject_id: str | None = None, limit: int = 3) -> dict:
    if subject_id:
        get_subject(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    rows = {}
    columns = {
        "subjects": "id,name",
        "knowledge_points": "id,subject_id,knowledge_key,title,archived,importance",
        "knowledge_mastery": "subject_id,knowledge_key,mastery,confidence,attempts,correct_attempts,last_reviewed_at,next_review_at,metadata",
        "topic_coverage": "knowledge_point_id",
        "exam_events": "id,subject_id,title,exam_date,status",
        "exam_topic_map": "exam_event_id,knowledge_point_id,weight",
        "review_tasks": "id,subject_id,title,estimated_minutes,scheduled_date,status",
    }
    # Bulk reads avoid a query per subject. Every service-role read carries owner scope.
    for table in ["subjects", "knowledge_points", "knowledge_mastery", "topic_coverage", "exam_events", "exam_topic_map", "review_tasks"]:
        query = client.table(table).select(columns[table]).eq("user_id", user_id)
        if subject_id:
            query = query.eq("id" if table == "subjects" else "subject_id", subject_id)
        if table == "knowledge_points": query = query.eq("archived", False)
        if table == "exam_events": query = query.eq("status", "active")
        if table == "review_tasks": query = query.in_("status", ["pending", "overdue"])
        # PostgREST defaults to a row cap. Read all relevant pages deterministically.
        order_key = {"topic_coverage": "knowledge_point_id", "exam_topic_map": "exam_event_id",
                     "knowledge_mastery": "subject_id"}.get(table, "id")
        query = query.order(order_key)
        if table == "exam_topic_map": query = query.order("knowledge_point_id")
        if table == "knowledge_mastery": query = query.order("knowledge_key")
        rows[table] = []
        offset = 0
        while True:
            page = query.range(offset, offset + 999).execute().data
            rows[table].extend(page)
            if len(page) < 1000: break
            offset += 1000
    return build_recommendations(subjects=rows["subjects"], topics=rows["knowledge_points"],
        mastery=rows["knowledge_mastery"], coverage=rows["topic_coverage"], events=rows["exam_events"],
        mappings=rows["exam_topic_map"], tasks=rows["review_tasks"], limit=limit)
