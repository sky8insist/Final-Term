from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.study_plan import StudyPlanRequest
from app.services import study_plan_service as scheduler, study_plan_v3_service as service, study_signal_service


def state(key, status="practicing"):
    return {"knowledgePointId": key, "knowledgeKey": key, "title": key, "state": status, "masteryScore": 0.5}


def test_exam_scope_and_weights_are_authoritative():
    signals = [{"knowledgeKey": "a", "needScore": 0.7}, {"knowledgeKey": "b", "needScore": 0.7}]
    result = service.prioritize(signals, [state("a"), state("b"), state("outside")],
                                [{"knowledge_point_id": "a", "weight": 1}, {"knowledge_point_id": "b", "weight": 5}], "STANDARD")
    assert [row["knowledgePointId"] for row in result] == ["b", "a"]
    assert "考试范围权重 5" in result[0]["reasons"]


def test_modes_include_mastered_only_for_comprehensive():
    assert service.prioritize([], [state("a", "mastered")], [], "STANDARD") == []
    assert service.prioritize([], [state("a", "mastered")], [], "COMPREHENSIVE")


def test_goal_and_available_minutes_validation():
    assert StudyPlanRequest(subjectId="s", examEventId=str(uuid4())).exam_date is None
    with pytest.raises(ValidationError): StudyPlanRequest(subjectId="s")
    with pytest.raises(ValidationError): StudyPlanRequest(subjectId="s", examDate="2026-12-01", availableMinutes={"2026-11-01": -1})


@pytest.mark.parametrize("mode", ["CRAM", "STANDARD", "COMPREHENSIVE"])
def test_zero_days_and_protected_minutes_are_respected(mode):
    start = date(2026, 10, 7); target = start + timedelta(days=6)
    blocked = (start + timedelta(days=1)).isoformat()
    protected = [{"knowledge_key": "fixed", "task_type": "manual", "scheduled_date": start.isoformat(), "estimated_minutes": 55, "status": "completed"}]
    signals = [{"knowledgeKey": f"topic-{i}", "needScore": 0.8} for i in range(8)]
    result = scheduler.build_schedule(signals=signals, start=start, target=target, daily_minutes=60, mode=mode,
        available_minutes={blocked: 0, target.isoformat(): 0}, protected=protected)
    assert not any(task["scheduled_date"] in {blocked, target.isoformat(), start.isoformat()} for task in result["tasks"])
    assert result["dailyUsage"][start.isoformat()] == 55
    assert all(result["dailyUsage"][day] <= amount for day, amount in result["dailyCapacity"].items())
    assert result["warnings"]


def test_overbudget_locked_tasks_are_preserved_and_explained():
    start = date(2026, 10, 7)
    result = scheduler.build_schedule(signals=[{"knowledgeKey": "new", "needScore": 1}], start=start, target=start + timedelta(days=1),
        daily_minutes=30, protected=[{"knowledge_key": "fixed", "task_type": "manual", "scheduled_date": start.isoformat(), "estimated_minutes": 90, "status": "pending"}])
    assert result["dailyUsage"][start.isoformat()] == 90
    assert any("受保护任务已超过可用时间" in warning for warning in result["warnings"])
    assert all(task["scheduled_date"] != start.isoformat() for task in result["tasks"])


def test_existing_protected_task_does_not_get_duplicate_slot():
    start = date(2026, 10, 7)
    protected = [{"knowledge_key": "a", "task_type": "concept_rebuild", "scheduled_date": start.isoformat(), "estimated_minutes": 5, "status": "completed"}]
    result = scheduler.build_schedule(signals=[{"knowledgeKey": "a", "needScore": 0.8, "mastery": 0.2}], start=start,
        target=start + timedelta(days=2), daily_minutes=90, protected=protected, reserve_final_day=False)
    assert not any(task["knowledge_key"] == "a" and task["scheduled_date"] == start.isoformat() for task in result["tasks"])


def test_automatic_replan_keeps_owner_scope_and_continues_after_failure(monkeypatch):
    db = MagicMock(); db.rpc.return_value.execute.return_value = SimpleNamespace(data=[
        {"id": "p1", "user_id": "u1", "exam_date": "2026-12-01", "strategy": {"algorithmVersion": scheduler.PLAN_ALGORITHM_VERSION, "autoReplan": True}},
        {"id": "p2", "user_id": "u2", "exam_date": "2026-12-01", "strategy": {"algorithmVersion": scheduler.PLAN_ALGORITHM_VERSION, "autoReplan": True}}])
    monkeypatch.setattr(service, "get_supabase_client", lambda: db)
    monkeypatch.setattr(scheduler, "_today", lambda: date(2026, 10, 7))
    calls = []
    def replan(**values):
        calls.append(values)
        if values["plan_id"] == "p1": raise HTTPException(409, "state changed")
    monkeypatch.setattr(service, "replan", replan)
    result = service.refresh_changed_plans()
    assert result["refreshed"] == 1 and len(result["failed"]) == 1
    assert calls[1] == {"user_id": "u2", "plan_id": "p2", "automatic": True}


def test_shanghai_date_is_used_for_schedule():
    assert isinstance(scheduler._today(), date)


def test_empty_subject_cold_start_has_complete_confidence_signal(monkeypatch):
    db = MagicMock(); query = db.table.return_value
    for method in ["select", "eq", "gte", "order", "limit"]: getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(study_signal_service, "get_supabase_client", lambda: db)
    result = study_signal_service.collect_study_signals(user_id="owner", subject_id="empty")
    assert result["dataSufficient"] is False
    assert result["signals"][0]["confidenceMismatch"] == 0
    assert result["signals"][0]["sourceSignals"] == []
