from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo
from urllib.parse import quote

from fastapi import HTTPException

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import study_signal_service
from app.services.llm_service import LLMServiceError, generate_json_async

PLAN_ALGORITHM_VERSION = "exam-state-scheduler-v3"


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _priority(item: dict, days_remaining: int) -> float:
    if "needScore" in item:
        return float(item["needScore"])
    score, _ = study_signal_service.calculate_need_score({
        "mastery": item.get("mastery", 0.5), "confidence": item.get("confidence", 0),
        "importance": (item.get("metadata") or {}).get("importance", 0.5),
        "prerequisiteWeight": (item.get("metadata") or {}).get("prerequisiteWeight", 0),
        "lastReviewedAt": (datetime.now(UTC) - timedelta(days=max(days_remaining, 1))).isoformat(),
    })
    return score


def _target_date(value: str, *, require_tomorrow: bool = True) -> date:
    try:
        target = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标日期必须使用 YYYY-MM-DD 格式") from exc
    minimum = _today() + timedelta(days=1) if require_tomorrow else _today()
    if target < minimum:
        raise HTTPException(status_code=422, detail="目标日期不能早于明天")
    return target


def build_phases(*, start: date, target: date, mode: str | None = None) -> list[dict]:
    day_count = (target - start).days + 1
    remaining = (target - start).days
    if mode == "CRAM" or (mode is None and remaining <= 3):
        labels = [("快速诊断", "确认薄弱点与高频题型"), ("薄弱点强化", "集中修补最高优先级知识点"),
                  ("高频题型", "用混合练习检验迁移"), ("模拟与总复盘", "限时检验并收束最后缺口")]
    elif mode == "STANDARD" or (mode is None and remaining <= 14):
        labels = [("基础修补", "重建薄弱概念与前置关系"), ("重点强化", "强化高优先级知识点"),
                  ("混合练习", "交错练习并识别混淆点"), ("模拟检验", "用综合练习验证掌握度"),
                  ("考前收束", "回顾关键结论与失分模式")]
    else:
        labels = [("基础重建", "系统恢复概念框架"), ("间隔复习", "用回忆测试巩固长期记忆"),
                  ("跨知识点应用", "训练知识迁移与综合表达"), ("周期性检测", "定期检测并调整优先级"),
                  ("模拟考试", "在限时条件下完成综合检验"), ("最终复盘", "收束遗留问题并稳定答题策略")]
    phase_count = min(len(labels), day_count)
    if phase_count < len(labels):
        if phase_count == 2:
            labels = [(f"{labels[0][0]}与{labels[1][0]}", f"{labels[0][1]}；{labels[1][1]}"),
                      (f"{labels[-2][0]}与{labels[-1][0]}", f"{labels[-2][1]}；{labels[-1][1]}")]
        else:
            labels = labels[:phase_count - 1] + [(f"{labels[-2][0]}与{labels[-1][0]}", f"{labels[-2][1]}；{labels[-1][1]}")]
    phases, cursor, days_left = [], start, day_count
    for index, (name, goal) in enumerate(labels):
        span = ceil(days_left / (len(labels) - index))
        end = min(cursor + timedelta(days=span - 1), target)
        phases.append({"id": f"phase-{index + 1}", "name": name, "goal": goal,
                       "startDate": cursor.isoformat(), "endDate": end.isoformat()})
        days_left -= (end - cursor).days + 1
        cursor = end + timedelta(days=1)
    return phases


def _phase_for(day: date, phases: list[dict]) -> dict:
    return next(p for p in phases if date.fromisoformat(p["startDate"]) <= day <= date.fromisoformat(p["endDate"]))


def _method_for(signal: dict, *, final: bool = False) -> dict:
    if final:
        return {"method": "限时模拟 + 结果复盘", "type": "mock_and_review",
                "criteria": "在限定时间内完成综合练习，复盘全部失分点并写出规避策略。",
                "types": ["single_choice", "short_answer"], "count": 8}
    accuracy, mastery = float(signal.get("accuracy", 0)), float(signal.get("mastery", 0.5))
    feedback = " ".join(signal.get("subjectiveFeedback") or [])
    if int(signal.get("dialogueEventCount", 0)) >= 2 or int(signal.get("hintRequestCount", 0)) >= 2 or "表达" in feedback:
        return {"method": "AI 学习室苏格拉底追问", "type": "socratic_dialogue",
                "criteria": "不查看完整答案，独立完成两轮追问并给出结构完整的解释。", "types": ["short_answer"], "count": 2}
    if int(signal.get("attemptCount", 0)) and accuracy < 0.6:
        return {"method": "小规模专项练习", "type": "targeted_practice",
                "criteria": "完成 5 道专项题，正确率达到 80%，并解释关键判断。", "types": ["single_choice", "true_false"], "count": 5}
    if mastery < 0.55:
        return {"method": "资料阅读 + 费曼讲解", "type": "concept_rebuild",
                "criteria": "能不看资料解释核心定义、适用条件和一个例子。", "types": ["true_false", "single_choice"], "count": 5}
    if float(signal.get("needComponents", {}).get("forgetting", 0)) >= 0.6:
        return {"method": "快速回忆测试 + 间隔复习", "type": "retrieval_practice",
                "criteria": "三分钟内写出关键结论，核对资料后补全遗漏。", "types": ["fill_blank", "short_answer"], "count": 4}
    return {"method": "对比表 + 判断题", "type": "compare_and_check",
            "criteria": "完成概念对比表，并在 5 道判断题中达到 80% 正确率。", "types": ["true_false", "single_choice"], "count": 5}


def build_schedule(*, signals: list[dict], start: date, target: date,
                   daily_minutes: int, reserve_final_day: bool = True,
                   weekend_extra: bool = False, mode: str | None = None,
                   available_minutes: dict[str, int] | None = None, protected: list[dict] | None = None) -> dict:
    phases = build_phases(start=start, target=target, mode=mode)
    days = [start + timedelta(days=i) for i in range((target - start).days + 1)]
    usage, tasks, warnings = {day: 0 for day in days}, [], []
    normal_days = days[:-1] if reserve_final_day and len(days) > 1 else days

    def capacity(day: date) -> int:
        if available_minutes and day.isoformat() in available_minutes:
            return available_minutes[day.isoformat()]
        return daily_minutes + min(30, daily_minutes // 2) if weekend_extra and day.weekday() >= 5 else daily_minutes

    occupied = set()
    for row in protected or []:
        occupied.add((row.get("knowledge_key"), str(row["scheduled_date"]), row.get("task_type")))
        day = date.fromisoformat(str(row["scheduled_date"]))
        if day in usage and row.get("status") != "skipped": usage[day] += int(row["estimated_minutes"])
        elif row.get("status") in {"pending", "overdue"}:
            warnings.append(f"受保护任务 {row.get('title', row.get('knowledge_key'))} 在当前日期范围之外，需手动调整")
    for day in days:
        if usage[day] > capacity(day): warnings.append(f"{day.isoformat()}：受保护任务已超过可用时间，保留任务并停止新增")

    def place(signal: dict, earliest: date, occurrence: int) -> bool:
        method = _method_for(signal)
        estimate = min(max(20 + round(float(signal.get("needScore", 0.5)) * 15), 20), 35)
        if mode == "CRAM": estimate = max(15, estimate - 10)
        if mode == "COMPREHENSIVE": estimate += 10
        candidates = [day for day in normal_days if day >= earliest and usage[day] + estimate <= capacity(day)
                      and (signal["knowledgeKey"], day.isoformat(), method["type"]) not in occupied]
        if not candidates:
            return False
        chosen = min(candidates, key=lambda day: (usage[day], day))
        usage[chosen] += estimate
        phase, key = _phase_for(chosen, phases), signal["knowledgeKey"]
        topic = quote(str(key), safe="")
        tasks.append({"knowledge_key": key, "task_type": method["type"], "title": signal.get("title") or key,
                      "scheduled_date": chosen.isoformat(), "estimated_minutes": estimate,
                      "priority": float(signal.get("needScore", 0.5)),
                      "metadata": {"phaseId": phase["id"], "method": method["method"],
                                   "reason": "；".join(signal.get("reasons") or ["依据课程重要度安排"]),
                                   "successCriteria": method["criteria"],
                                   "sourceSignals": list(signal.get("sourceSignals") or []) or ["course"],
                                   "recommendedQuestionTypes": method["types"], "recommendedQuestionCount": method["count"],
                                   "resourceLinks": [{"type": "study-room", "href": f"/study-room?topic={topic}", "label": "进入 AI 学习室"},
                                                     {"type": "practice", "href": f"/exams?topic={topic}", "label": "生成专项练习"},
                                                     {"type": "mind-map", "href": f"/mind-map?topic={topic}", "label": "查看思维导图"},
                                                     {"type": "materials", "href": f"/materials?topic={topic}", "label": "打开课程资料"}],
                                   "masteryAtCreation": signal.get("mastery", 0.5), "recentAccuracy": signal.get("accuracy", 0),
                                   "needScore": signal.get("needScore", 0.5), "needComponents": signal.get("needComponents", {}),
                                   "spacingOccurrence": occurrence}})
        return True

    ranked = sorted(signals, key=lambda item: (-float(item.get("needScore", 0)), item.get("knowledgeKey", "")))
    for signal in ranked:
        if not place(signal, start, 0):
            warnings.append(f"每日时间不足，未能安排：{signal.get('title') or signal['knowledgeKey']}")
    repeat_signals = ranked if mode == "COMPREHENSIVE" else ranked[:max(1, min(5, len(ranked)))]
    for signal in repeat_signals:
        existing = [date.fromisoformat(t["scheduled_date"]) for t in tasks if t["knowledge_key"] == signal["knowledgeKey"]]
        if existing:
            if mode != "CRAM": place(signal, existing[-1] + timedelta(days=3), 1)
    if reserve_final_day:
        final, method = days[-1], _method_for({}, final=True)
        estimate = min(30, max(0, capacity(final) - usage[final]))
        if estimate > 0 and ("综合模拟与总复盘", final.isoformat(), method["type"]) not in occupied:
            usage[final] += estimate
            tasks.append({"knowledge_key": "综合模拟与总复盘", "task_type": method["type"], "title": "限时模拟与总复盘",
                      "scheduled_date": final.isoformat(), "estimated_minutes": estimate, "priority": 1.0,
                      "metadata": {"phaseId": _phase_for(final, phases)["id"], "method": method["method"],
                                   "reason": "目标日期前保留综合检验，确认仍需收束的知识缺口。",
                                   "successCriteria": method["criteria"], "sourceSignals": ["practice", "dialogue"],
                                   "recommendedQuestionTypes": method["types"], "recommendedQuestionCount": method["count"],
                                   "resourceLinks": [{"type": "practice", "href": "/exams?mode=mock", "label": "开始限时模拟"}],
                                   "masteryAtCreation": None, "recentAccuracy": None, "spacingOccurrence": 0}})
        elif estimate == 0: warnings.append("最后一天没有剩余可用时间，未新增模拟任务")
    tasks.sort(key=lambda item: (item["scheduled_date"], -item["priority"], item["title"]))
    return {"phases": phases, "tasks": tasks, "dailyUsage": {day.isoformat(): value for day, value in usage.items()},
            "dailyCapacity": {day.isoformat(): capacity(day) for day in days}, "warnings": warnings}


def preview_plan(*, user_id: str, subject_id: str, exam_date: str | None, daily_minutes: int,
                 reserve_final_day: bool = True, weekend_extra: bool = False, **options) -> dict:
    from app.services.study_plan_v3_service import preview
    return preview(user_id=user_id, subject_id=subject_id, exam_date=exam_date, daily_minutes=daily_minutes,
                   reserve_final_day=reserve_final_day, weekend_extra=weekend_extra, **options)


def generate_plan(*, user_id: str, subject_id: str, exam_date: str | None, daily_minutes: int, title: str,
                  weekend_extra: bool = False, reserve_final_day: bool = True, preserve_existing: bool = True,
                  **options) -> dict:
    from app.services.study_plan_v3_service import generate
    return generate(user_id=user_id, subject_id=subject_id, exam_date=exam_date, daily_minutes=daily_minutes,
                    title=title, weekend_extra=weekend_extra, reserve_final_day=reserve_final_day,
                    preserve_existing=preserve_existing, **options)


async def enrich_task_guidance(*, user_id: str, plan: dict, tasks: list[dict]) -> list[dict]:
    """Let the model refine learning guidance without changing dates, duration, or priority."""
    candidates = [task for task in tasks if task.get("source") == "system"][:80]
    if not candidates:
        return tasks
    compact = [{"id": task["id"], "knowledgeKey": task.get("knowledge_key"),
                "taskType": task.get("task_type"), "metadata": {
                    "method": (task.get("metadata") or {}).get("method"),
                    "reason": (task.get("metadata") or {}).get("reason"),
                    "successCriteria": (task.get("metadata") or {}).get("successCriteria"),
                }} for task in candidates]
    prompt = f"""你是复习任务设计器。只优化任务的学习方法和可验证完成标准，不得改变日期、时长、知识点或优先级。
根据任务类型选择资料阅读、费曼讲解、对比表、闪卡、案例题、苏格拉底追问、专项练习、回忆测试或限时模拟。
严格返回 JSON：{{"tasks":[{{"id":"","method":"","successCriteria":""}}]}}。
每项 method 不超过 40 字，successCriteria 必须可观测且不超过 100 字。任务：{json.dumps(compact, ensure_ascii=False)}"""
    try:
        result = await generate_json_async(prompt, timeout=45)
    except (LLMServiceError, ValueError, TypeError):
        return tasks
    allowed = {task["id"]: task for task in candidates}
    updates = {}
    client = get_supabase_client()
    for item in result.get("tasks") or []:
        task = allowed.get(str(item.get("id")))
        method = str(item.get("method") or "").strip()
        criteria = str(item.get("successCriteria") or "").strip()
        if not task or not method or not criteria or len(method) > 80 or len(criteria) > 200:
            continue
        metadata = {**(task.get("metadata") or {}), "method": method, "successCriteria": criteria,
                    "guidanceModel": settings.llm_model}
        try:
            rows = (client.table("review_tasks").update({"metadata": metadata})
                    .eq("id", task["id"]).eq("user_id", user_id).eq("source", "system").eq("locked", False)
                    .eq("status", "pending").select("*").execute().data)
        except Exception:
            continue
        if rows:
            updates[task["id"]] = rows[0]
    if updates:
        strategy = {**(plan.get("strategy") or {}), "model": settings.llm_model,
                    "guidanceGeneratedAt": datetime.now(UTC).isoformat(), "aiGuidanceTaskCount": len(updates)}
        try:
            client.table("study_plans").update({"strategy": strategy}).eq("id", plan["id"]).eq("user_id", user_id).eq("version", plan["version"]).execute()
        except Exception:
            pass
    return [updates.get(task["id"], task) for task in tasks]


def today_tasks(*, user_id: str, subject_id: str | None = None) -> list[dict]:
    query = get_supabase_client().table("review_tasks").select("*").eq("user_id", user_id).lte("scheduled_date", _today().isoformat()).in_("status", ["pending", "overdue"]).order("priority", desc=True)
    return (query.eq("subject_id", subject_id) if subject_id else query).execute().data


def plan_overview(*, user_id: str, subject_id: str | None = None) -> dict:
    client = get_supabase_client()
    query = client.table("study_plans").select("*").eq("user_id", user_id).order("created_at", desc=True)
    plans = (query.eq("subject_id", subject_id) if subject_id else query).execute().data
    active = next((p for p in plans if p.get("status") == "active"), plans[0] if plans else None)
    tasks = (client.table("review_tasks").select("*").eq("user_id", user_id).eq("plan_id", active["id"]).order("scheduled_date").limit(1000).execute().data if active else [])
    completed = sum(1 for item in tasks if item.get("status") == "completed")
    return {"plans": plans, "activePlan": active, "tasks": tasks,
            "summary": {"total": len(tasks), "completed": completed, "completionRate": completed / len(tasks) if tasks else 0,
                        "overdue": sum(1 for item in tasks if item.get("status") == "overdue"),
                        "scheduledMinutes": sum(int(item.get("estimated_minutes", 0)) for item in tasks)}}


def activate_sprint(*, user_id: str, plan_id: str) -> dict:
    rows = get_supabase_client().table("study_plans").select("*").eq("id", plan_id).eq("user_id", user_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Study plan not found")
    plan = rows[0]
    from app.services.study_plan_v3_service import replan
    result = replan(user_id=user_id, plan_id=plan["id"], mode="CRAM")
    return {"plan": result["plan"], "rescheduled": len(result["tasks"])}


def update_task(*, user_id: str, task_id: str, task_status: str | None,
                scheduled_date: str | None = None, estimated_minutes: int | None = None, locked: bool | None = None) -> dict:
    if task_status is not None and task_status not in {"pending", "completed", "skipped"}:
        raise HTTPException(status_code=422, detail="Invalid review task status")
    payload: dict = {"source": "user"}
    if locked is not None:
        payload["locked"] = locked
        if task_status is None and scheduled_date is None and estimated_minutes is None: payload.pop("source")
    if task_status is not None:
        payload.update({"status": task_status, "completed_at": datetime.now(UTC).isoformat() if task_status == "completed" else None})
    if scheduled_date is not None:
        try:
            date.fromisoformat(scheduled_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="scheduledDate must use YYYY-MM-DD") from exc
        payload["scheduled_date"] = scheduled_date
    if estimated_minutes is not None:
        payload["estimated_minutes"] = estimated_minutes
    if payload == {"source": "user"}:
        raise HTTPException(status_code=422, detail="No review task changes were provided")
    response = get_supabase_client().table("review_tasks").update(payload).eq("id", task_id).eq("user_id", user_id).select("*").execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Review task not found")
    return response.data[0]


def rebalance_active_plans(*, user_id: str, daily_minutes: int) -> int:
    client = get_supabase_client()
    plans = client.table("study_plans").select("*").eq("user_id", user_id).eq("status", "active").execute().data
    changed = 0
    for plan in plans:
        from app.services.study_plan_v3_service import replan
        result = replan(user_id=user_id, plan_id=plan["id"], daily_minutes=daily_minutes)
        changed += sum(1 for task in result["tasks"] if task.get("source") == "system")
    return changed
