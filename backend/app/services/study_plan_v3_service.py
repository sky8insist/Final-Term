from datetime import date

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services import learner_state_service, study_signal_service
from app.services.course_service import _owned


def prioritize(signals: list[dict], states: list[dict], mappings: list[dict], mode: str) -> list[dict]:
    """Only authoritative active Topics may produce tasks; exam scope is explicit."""
    by_key = {row["knowledgeKey"]: row for row in signals}
    weights = {row["knowledge_point_id"]: float(row["weight"]) for row in mappings}
    maximum = max(weights.values(), default=1) or 1
    result = []
    for state in states:
        if mappings and state["knowledgePointId"] not in weights: continue
        if mode != "COMPREHENSIVE" and state["state"] == "mastered": continue
        source = by_key.get(state["knowledgeKey"], {})
        weight = weights.get(state["knowledgePointId"], 1) / maximum
        score = min(1.0, float(source.get("needScore", 0.5)) * (0.65 + 0.35 * weight)
                    + (0.2 if state["state"] == "at_risk" else 0)
                    + (0.1 if state["state"] == "not_started" and mode == "COMPREHENSIVE" else 0))
        reasons = list(source.get("reasons") or []) + [f"学习状态：{state['state']}"]
        if mappings: reasons.append(f"考试范围权重 {weights[state['knowledgePointId']]:g}")
        result.append({**source, "knowledgeKey": state["knowledgeKey"], "knowledgePointId": state["knowledgePointId"],
                       "title": state["title"], "mastery": state["masteryScore"], "needScore": score, "reasons": reasons})
    return sorted(result, key=lambda row: (-row["needScore"], row["knowledgeKey"]))


def prepare(*, user_id: str, subject_id: str, exam_date: str | None, daily_minutes: int,
            reserve_final_day: bool, weekend_extra: bool, exam_event_id: str | None = None,
            mode: str = "STANDARD", available_minutes: dict | None = None, preserve_existing: bool = True) -> dict:
    from app.services.study_plan_service import _target_date, _today, build_schedule
    client = get_supabase_client()
    from app.services.subject_service import get_subject
    get_subject(user_id=user_id, subject_id=subject_id)
    event, mappings = None, []
    if exam_event_id:
        event = _owned(table="exam_events", row_id=str(exam_event_id), user_id=user_id, subject_id=subject_id)
        if event["status"] != "active": raise HTTPException(422, "考试目标已结束或归档")
        exam_date = event["exam_date"]
        mappings = (client.table("exam_topic_map").select("knowledge_point_id,weight").eq("user_id", user_id)
                    .eq("subject_id", subject_id).eq("exam_event_id", str(exam_event_id)).execute().data)
        if not mappings: raise HTTPException(422, "考试目标未配置知识点范围")
    if not exam_date: raise HTTPException(422, "需要目标日期或考试目标")
    target, today = _target_date(str(exam_date)), _today()
    if (target - today).days > 365: raise HTTPException(422, "计划最多覆盖一年")
    available = {str(day): amount for day, amount in (available_minutes or {}).items()}
    if any(not today <= date.fromisoformat(day) <= target for day in available):
        raise HTTPException(422, "逐日可用时间必须处于计划日期范围内")
    if mode not in {"CRAM", "STANDARD", "COMPREHENSIVE"}: raise HTTPException(422, "无效的计划模式")
    existing = (client.table("study_plans").select("*").eq("user_id", user_id).eq("subject_id", subject_id)
                .eq("status", "active").order("created_at", desc=True).limit(1).execute().data)
    plan = existing[0] if existing else None
    # Global day budgets are shared with other subjects; this plan's protected
    # tasks are deducted separately by build_schedule. The save RPC rechecks
    # capacity under the same user lock as calendar edits and other plan saves.
    shared = client.rpc('calendar_plan_capacity', {'p_user':user_id,'p_start':today.isoformat(),
        'p_end':target.isoformat(),'p_plan':plan['id'] if plan else None}).execute().data
    requested_available = dict(available)
    for day, minutes in shared.items():
        normal = daily_minutes + (min(30, daily_minutes // 2) if weekend_extra and date.fromisoformat(day).weekday() >= 5 else 0)
        available[day] = min(available.get(day, normal), minutes)
    observations = study_signal_service.collect_study_signals(user_id=user_id, subject_id=subject_id)
    states = learner_state_service.list_states(user_id=user_id, subject_id=subject_id)["topics"]
    signals = prioritize(observations["signals"], states, mappings, mode)
    if mappings and not any(state["knowledgePointId"] in {row["knowledge_point_id"] for row in mappings} for state in states):
        raise HTTPException(422, "考试范围全部已归档，请更新范围")
    old = (client.table("review_tasks").select("*").eq("user_id", user_id).eq("plan_id", plan["id"])
           .order("scheduled_date").execute().data) if plan and preserve_existing else []
    protected = [row for row in old if row["status"] == "completed" or row["source"] == "user" or row.get("locked")]
    schedule = build_schedule(signals=signals, start=today, target=target, daily_minutes=daily_minutes,
                              reserve_final_day=reserve_final_day, weekend_extra=weekend_extra, mode=mode,
                              available_minutes=available, protected=protected)
    by_key = {state["knowledgeKey"]: state for state in states}
    for task in schedule["tasks"]:
        state = by_key.get(task["knowledge_key"])
        task["knowledge_point_id"] = state["knowledgePointId"] if state else None
        if state:
            task["metadata"]["resourceLinks"].insert(0, {"type": "guided-study", "label": "开始引导学习",
                "href": f"/guided-study?topicId={state['knowledgePointId']}" + (f"&examEventId={exam_event_id}" if exam_event_id else "")})
    missed = sum(row["scheduled_date"] < today.isoformat() and row["status"] in {"pending", "overdue"} for row in old)
    warnings = list(dict.fromkeys(observations["warnings"] + schedule["warnings"]))
    if missed: warnings.append(f"有 {missed} 项历史未完成任务；自动任务重排到剩余日期，手动或锁定任务保留原日期")
    return {"plan": plan, "event": event, "protected": protected, "signals": signals, "observations": observations,
            "schedule": schedule, "warnings": warnings, "target": target, "today": today, "available": requested_available}


def preview(**values) -> dict:
    ctx = prepare(**values)
    schedule, target, today = ctx["schedule"], ctx["target"], ctx["today"]
    return {"targetDate": target.isoformat(), "daysRemaining": (target - today).days,
            "dataSufficient": ctx["observations"]["dataSufficient"], "signalStats": ctx["observations"]["stats"],
            "estimatedKnowledgePoints": len({task["knowledge_point_id"] for task in schedule["tasks"] if task["knowledge_point_id"]}),
            "estimatedMinutes": sum(task["estimated_minutes"] for task in schedule["tasks"]),
            "availableMinutes": sum(schedule["dailyCapacity"].values()), "timeSufficient": not schedule["warnings"],
            "warnings": ctx["warnings"], "phases": schedule["phases"], "dailyUsage": schedule["dailyUsage"],
            "preservedTaskCount": len(ctx["protected"]), "mode": values.get("mode", "STANDARD")}


def generate(*, title: str, auto_replan: bool = True, reason: str = "用户生成计划", **values) -> dict:
    from app.services.study_plan_service import PLAN_ALGORITHM_VERSION
    ctx = prepare(**values)
    schedule, observations, plan = ctx["schedule"], ctx["observations"], ctx["plan"]
    strategy = {"algorithmVersion": PLAN_ALGORITHM_VERSION, "signalAlgorithmVersion": observations["algorithmVersion"],
                "mode": values.get("mode", "STANDARD"), "dailyMinutes": values["daily_minutes"],
                "weekendExtra": values["weekend_extra"], "reserveFinalDay": values["reserve_final_day"],
                "availableMinutes": ctx["available"], "autoReplan": auto_replan, "timezone": "Asia/Shanghai",
                "examGoal": ctx["event"], "targetDate": ctx["target"].isoformat(),
                "signalStats": observations["stats"], "dataSufficient": observations["dataSufficient"],
                "priorityReasons": [{"knowledgePointId": row["knowledgePointId"], "reasons": row["reasons"], "needScore": row["needScore"]} for row in ctx["signals"]],
                "warnings": ctx["warnings"], "preservedTaskCount": len(ctx["protected"]),
                "phases": schedule["phases"], "dailyUsage": schedule["dailyUsage"], "dailyCapacity": schedule["dailyCapacity"],
                "model": "deterministic-method-selector-v3", "generatedDate": ctx["today"].isoformat()}
    try:
        result = get_supabase_client().rpc("save_study_plan_v3", {"p_user_id": values["user_id"], "p_subject_id": values["subject_id"],
            "p_plan_id": plan["id"] if plan else None, "p_expected_version": plan["version"] if plan else 0,
            "p_values": {"title": title, "exam_date": ctx["target"].isoformat(), "daily_minutes": values["daily_minutes"],
                         "mode": values.get("mode", "STANDARD"), "exam_event_id": values.get("exam_event_id"), "strategy": strategy, "reason": reason},
            "p_tasks": schedule["tasks"], "p_preserve": values.get("preserve_existing", True)}).execute().data
    except Exception as exc:
        if getattr(exc, "code", None) in {"40001", "40P01"}: raise HTTPException(409, "计划或学习状态已更新，请重试重排") from exc
        raise
    saved = result[0] if isinstance(result, list) else result
    tasks = (get_supabase_client().table("review_tasks").select("*").eq("user_id", values["user_id"])
             .eq("plan_id", saved["id"]).order("scheduled_date").execute().data)
    return {"plan": saved, "tasks": tasks}


def replan(*, user_id: str, plan_id: str, automatic: bool = False,
           daily_minutes: int | None = None, mode: str | None = None) -> dict:
    rows = get_supabase_client().table("study_plans").select("*").eq("id", plan_id).eq("user_id", user_id).limit(1).execute().data
    if not rows: raise HTTPException(404, "复习计划不存在")
    plan = rows[0]
    if plan["status"] != "active": raise HTTPException(409, "只能重排活动计划")
    strategy = plan.get("strategy") or {}
    from app.services.study_plan_service import _today
    available = {day: amount for day, amount in strategy.get("availableMinutes", {}).items() if day >= _today().isoformat()}
    return generate(user_id=user_id, subject_id=plan["subject_id"], exam_date=plan["exam_date"], title=plan["title"],
        daily_minutes=daily_minutes if daily_minutes is not None else plan["daily_minutes"], weekend_extra=strategy.get("weekendExtra", False),
        reserve_final_day=strategy.get("reserveFinalDay", True), preserve_existing=True, mode=mode or plan.get("mode", "STANDARD"),
        exam_event_id=plan.get("exam_event_id"), available_minutes=available, auto_replan=strategy.get("autoReplan", True),
        reason=("自动重排：" if automatic else "用户重排：") + (plan.get("replan_reason") or "未完成任务与当前学习状态"))


def refresh_changed_plans() -> dict:
    """Bounded deterministic refresh. Celery Beat is required; no model calls."""
    from app.services.study_plan_service import PLAN_ALGORITHM_VERSION, _today
    client = get_supabase_client()
    plans = client.rpc("study_plan_replan_candidates", {}).execute().data
    refreshed, skipped, failed = 0, 0, []
    for plan in plans:
        strategy = plan.get("strategy") or {}
        if strategy.get("algorithmVersion") != PLAN_ALGORITHM_VERSION or not strategy.get("autoReplan", False): continue
        if date.fromisoformat(plan["exam_date"]) <= _today(): skipped += 1; continue
        try:
            replan(user_id=plan["user_id"], plan_id=plan["id"], automatic=True)
            refreshed += 1
        except Exception as exc:
            failed.append({"planId": plan["id"], "error": str(exc)[:300]})
        if refreshed + len(failed) >= 20: break
    return {"refreshed": refreshed, "expiredSkipped": skipped, "failed": failed}
