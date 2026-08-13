from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.mastery_service import list_mastery


def _priority(item: dict, days_remaining: int) -> float:
    mastery_gap = 1 - float(item.get("mastery", 0.5))
    confidence_gap = 1 - float(item.get("confidence", 0))
    urgency = 1 / max(days_remaining, 1)
    importance = float(item.get("metadata", {}).get("importance", 0.5))
    prerequisite = float(item.get("metadata", {}).get("prerequisiteWeight", 0))
    return round(mastery_gap * 0.45 + confidence_gap * 0.15 + urgency * 0.15 + importance * 0.2 + prerequisite * 0.05, 4)


def generate_plan(*, user_id: str, subject_id: str, exam_date: str,
                  daily_minutes: int, title: str) -> dict:
    try:
        target_date = date.fromisoformat(exam_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="examDate must use YYYY-MM-DD") from exc
    today = date.today()
    if target_date < today:
        raise HTTPException(status_code=422, detail="examDate cannot be in the past")
    mastery = list_mastery(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    if not mastery:
        questions = client.table("questions").select("knowledge_key").eq("user_id", user_id).eq("subject_id", subject_id).execute().data
        keys = sorted({row["knowledge_key"] for row in questions}) or ["课程核心知识"]
        mastery = [{"knowledge_key": key, "mastery": 0.5, "confidence": 0, "metadata": {}} for key in keys]
    plan = client.table("study_plans").insert({
        "user_id": user_id, "subject_id": subject_id, "title": title,
        "exam_date": exam_date, "daily_minutes": daily_minutes,
        "strategy": {"algorithm": "mastery-spacing-v1", "knowledgeCount": len(mastery)},
    }).select("*").execute().data[0]
    days = max((target_date - today).days + 1, 1)
    ranked = sorted(mastery, key=lambda item: _priority(item, days), reverse=True)
    tasks = []
    day_usage = [0] * days
    for item in ranked:
        estimate = min(max(int(10 + (1 - float(item.get("mastery", 0.5))) * 30), 10), 40)
        next_review = item.get("next_review_at")
        try:
            first_due = max(today, datetime.fromisoformat(str(next_review).replace("Z", "+00:00")).date()) if next_review else today
        except ValueError:
            first_due = today
        interval = max(int(item.get("metadata", {}).get("intervalDays", 1)), 1)
        due = first_due
        occurrence = 0
        while due <= target_date and len(tasks) < 500:
            earliest = min(max((due - today).days, 0), days - 1)
            candidates = sorted(range(earliest, days), key=lambda day_index: (day_usage[day_index], day_index))
            day_index = next((candidate for candidate in candidates if day_usage[candidate] + estimate <= daily_minutes), candidates[0])
            day_usage[day_index] += estimate
            tasks.append({
                "user_id": user_id, "subject_id": subject_id, "plan_id": plan["id"],
                "knowledge_key": item["knowledge_key"], "task_type": "review_and_practice",
                "title": f"复习：{item['knowledge_key']}", "scheduled_date": (today + timedelta(days=day_index)).isoformat(),
                "estimated_minutes": estimate, "priority": _priority(item, days - day_index),
                "metadata": {"masteryAtCreation": item.get("mastery"), "confidenceAtCreation": item.get("confidence"),
                             "spacingOccurrence": occurrence, "spacingIntervalDays": interval},
            })
            occurrence += 1
            due = today + timedelta(days=day_index + interval)
            interval = min(max(round(interval * 1.7), interval + 1), 30)
    inserted = client.table("review_tasks").insert(tasks).select("*").execute().data if tasks else []
    return {"plan": plan, "tasks": inserted}


def today_tasks(*, user_id: str, subject_id: str | None = None) -> list[dict]:
    client = get_supabase_client()
    overdue = client.table("review_tasks").select("id").eq("user_id", user_id).lt("scheduled_date", date.today().isoformat()).eq("status", "pending")
    if subject_id:
        overdue = overdue.eq("subject_id", subject_id)
    overdue_ids = [row["id"] for row in overdue.execute().data]
    if overdue_ids:
        client.table("review_tasks").update({"status": "overdue"}).in_("id", overdue_ids).eq("user_id", user_id).execute()
    query = get_supabase_client().table("review_tasks").select("*").eq("user_id", user_id).lte("scheduled_date", date.today().isoformat()).in_("status", ["pending", "overdue"]).order("priority", desc=True)
    if subject_id:
        query = query.eq("subject_id", subject_id)
    return query.execute().data


def plan_overview(*, user_id: str, subject_id: str | None = None) -> dict:
    client = get_supabase_client()
    plans_query = client.table("study_plans").select("*").eq("user_id", user_id).order("created_at", desc=True)
    tasks_query = client.table("review_tasks").select("*").eq("user_id", user_id).order("scheduled_date")
    if subject_id:
        plans_query = plans_query.eq("subject_id", subject_id)
        tasks_query = tasks_query.eq("subject_id", subject_id)
    plans = plans_query.execute().data
    tasks = tasks_query.limit(1000).execute().data
    completed = sum(1 for item in tasks if item["status"] == "completed")
    return {
        "plans": plans, "tasks": tasks,
        "summary": {
            "total": len(tasks), "completed": completed,
            "completionRate": completed / len(tasks) if tasks else 0,
            "overdue": sum(1 for item in tasks if item["status"] == "overdue"),
            "scheduledMinutes": sum(int(item.get("estimated_minutes", 0)) for item in tasks),
        },
    }


def activate_sprint(*, user_id: str, plan_id: str) -> dict:
    client = get_supabase_client()
    rows = client.table("study_plans").select("*").eq("id", plan_id).eq("user_id", user_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Study plan not found")
    plan = rows[0]
    today = date.today()
    target = date.fromisoformat(str(plan["exam_date"]))
    days = max((target - today).days + 1, 1)
    daily_minutes = int(plan["daily_minutes"])
    tasks = (
        client.table("review_tasks").select("*").eq("user_id", user_id)
        .eq("plan_id", plan_id).eq("source", "system")
        .in_("status", ["pending", "overdue"]).order("priority", desc=True).execute().data
    )
    usage = [0] * days
    for task in tasks:
        minutes = int(task["estimated_minutes"])
        candidates = sorted(range(days), key=lambda index: (usage[index], index))
        selected = next((index for index in candidates if usage[index] + minutes <= daily_minutes), candidates[0])
        usage[selected] += minutes
        client.table("review_tasks").update({
            "scheduled_date": (today + timedelta(days=selected)).isoformat(),
            "status": "pending", "priority": min(float(task["priority"]) + 0.15, 1),
        }).eq("id", task["id"]).eq("user_id", user_id).execute()
    strategy = {**(plan.get("strategy") or {}), "mode": "sprint", "activatedAt": datetime.now().astimezone().isoformat()}
    updated = client.table("study_plans").update({"strategy": strategy}).eq("id", plan_id).eq("user_id", user_id).select("*").execute().data[0]
    return {"plan": updated, "rescheduled": len(tasks)}


def update_task(*, user_id: str, task_id: str, task_status: str | None,
                scheduled_date: str | None = None, estimated_minutes: int | None = None) -> dict:
    if task_status is not None and task_status not in {"pending", "completed", "skipped"}:
        raise HTTPException(status_code=422, detail="Invalid review task status")
    payload: dict = {"source": "user"}
    if task_status is not None:
        payload.update({"status": task_status, "completed_at": datetime.now().astimezone().isoformat() if task_status == "completed" else None})
    if scheduled_date is not None:
        try:
            date.fromisoformat(scheduled_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="scheduledDate must use YYYY-MM-DD") from exc
        payload["scheduled_date"] = scheduled_date
    if estimated_minutes is not None:
        payload["estimated_minutes"] = estimated_minutes
    if len(payload) == 1:
        raise HTTPException(status_code=422, detail="No review task changes were provided")
    response = get_supabase_client().table("review_tasks").update(payload).eq("id", task_id).eq("user_id", user_id).select("*").execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Review task not found")
    return response.data[0]


def rebalance_active_plans(*, user_id: str, daily_minutes: int) -> int:
    """Reflow system-owned pending tasks while preserving user adjustments."""
    client = get_supabase_client()
    plans = client.table("study_plans").select("*").eq("user_id", user_id).eq("status", "active").execute().data
    changed = 0
    today = date.today()
    for plan in plans:
        target = date.fromisoformat(str(plan["exam_date"]))
        day_count = max((target - today).days + 1, 1)
        usage = [0] * day_count
        occupied: set[tuple[str, int]] = set()
        manual = (
            client.table("review_tasks").select("knowledge_key,scheduled_date,estimated_minutes")
            .eq("user_id", user_id).eq("plan_id", plan["id"]).eq("source", "user")
            .in_("status", ["pending", "overdue"]).execute().data
        )
        for item in manual:
            offset = min(max((date.fromisoformat(str(item["scheduled_date"])) - today).days, 0), day_count - 1)
            usage[offset] += int(item["estimated_minutes"])
            occupied.add((str(item["knowledge_key"]), offset))
        system_tasks = (
            client.table("review_tasks").select("id,knowledge_key,scheduled_date,estimated_minutes")
            .eq("user_id", user_id).eq("plan_id", plan["id"]).eq("source", "system")
            .in_("status", ["pending", "overdue"]).order("priority", desc=True).execute().data
        )
        for task in system_tasks:
            old_offset = min(max((date.fromisoformat(str(task["scheduled_date"])) - today).days, 0), day_count - 1)
            occupied.add((str(task["knowledge_key"]), old_offset))
        for task in system_tasks:
            minutes = int(task["estimated_minutes"])
            old_offset = min(max((date.fromisoformat(str(task["scheduled_date"])) - today).days, 0), day_count - 1)
            occupied.discard((str(task["knowledge_key"]), old_offset))
            candidates = sorted(range(day_count), key=lambda index: (usage[index], index))
            available = [index for index in candidates if (str(task["knowledge_key"]), index) not in occupied]
            if not available:
                occupied.add((str(task["knowledge_key"]), old_offset))
                continue
            selected = next((index for index in available if usage[index] + minutes <= daily_minutes), available[0])
            usage[selected] += minutes
            occupied.add((str(task["knowledge_key"]), selected))
            client.table("review_tasks").update({
                "scheduled_date": (today + timedelta(days=selected)).isoformat(),
                "status": "pending",
            }).eq("id", task["id"]).eq("user_id", user_id).execute()
            changed += 1
        client.table("study_plans").update({"daily_minutes": daily_minutes}).eq("id", plan["id"]).eq("user_id", user_id).execute()
    return changed
