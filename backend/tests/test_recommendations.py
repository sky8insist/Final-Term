from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.services.recommendation_service import build_recommendations
from app.services import recommendation_service
from types import SimpleNamespace

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def base():
    return {"subjects": [{"id": "s", "name": "课程"}], "topics": [], "mastery": [], "coverage": [],
            "events": [], "mappings": [], "tasks": [], "now": NOW}


def topic(topic_id):
    return {"id": topic_id, "subject_id": "s", "knowledge_key": topic_id, "title": topic_id}


def test_recommendations_authenticate():
    assert TestClient(app).get("/api/v1/recommendations/next-actions").status_code == 401


def test_exam_in_three_days_prioritizes_weak_scoped_topic():
    args = base()
    args["topics"] = [topic("weak"), topic("other")]
    args["mastery"] = [{"subject_id": "s", "knowledge_key": key, "mastery": 0.3,
                        "confidence": 0.5, "attempts": 3, "correct_attempts": 1,
                        "last_reviewed_at": NOW.isoformat()} for key in ["weak", "other"]]
    args["events"] = [{"id": "exam", "subject_id": "s", "title": "期末", "exam_date": "2026-10-10", "status": "active"}]
    args["mappings"] = [{"exam_event_id": "exam", "knowledge_point_id": "weak", "weight": 5}]
    result = build_recommendations(**args)
    assert result["actions"][0]["knowledgePointId"] == "weak"
    assert "3 天后考试" in result["actions"][0]["reasons"][0]


def test_expired_or_archived_exams_do_not_boost_priority():
    args = base()
    args["topics"] = [topic("t")]
    baseline = build_recommendations(**args)["actions"][0]["priorityScore"]
    args["events"] = [{"id": "e", "subject_id": "s", "title": "过去", "exam_date": "2026-10-06", "status": "active"}]
    args["mappings"] = [{"exam_event_id": "e", "knowledge_point_id": "t", "weight": 1}]
    assert build_recommendations(**args)["actions"][0]["priorityScore"] == baseline
    args["events"][0].update(status="archived", exam_date="2026-10-08")
    assert build_recommendations(**args)["upcomingExams"] == []


def test_cold_start_is_explicit_without_fabricated_mastery():
    result = build_recommendations(**base())
    assert result["coldStart"]
    assert result["actions"][0]["masteryScore"] is None
    assert result["actions"][0]["actionType"] == "setup"


def test_archived_topics_excluded_and_only_owned_subjects_used():
    args = base()
    args["topics"] = [{**topic("archived"), "archived": True}, {**topic("foreign"), "subject_id": "other"}]
    result = build_recommendations(**args)
    assert all(action["knowledgePointId"] is None for action in result["actions"])


def test_mastered_topic_without_due_review_is_not_recommended():
    args = base()
    args["topics"] = [topic("t")]
    args["mastery"] = [{"subject_id": "s", "knowledge_key": "t", "mastery": 0.9,
                         "confidence": 1, "attempts": 6, "metadata": {"assessmentCount": 6, "assessmentCorrectStreak": 6},
                         "next_review_at": "2026-10-09T00:00:00Z"}]
    assert build_recommendations(**args)["actions"] == []
    args["mastery"][0]["next_review_at"] = "2026-10-06T00:00:00Z"
    assert build_recommendations(**args)["dueReviewCount"] == 1


def test_bulk_queries_preserve_owner_subject_scope_and_paginate(monkeypatch):
    pages = []
    data = {"subjects": [{"id": "s", "name": "课程"}],
            "knowledge_points": [topic(str(index)) for index in range(1001)]}
    class Query:
        def __init__(self, name): self.name, self.filters, self.offset = name, {}, 0
        def select(self, *_): return self
        def eq(self, key, value): self.filters[key] = value; return self
        def in_(self, *_): return self
        def order(self, *_): return self
        def range(self, offset, *_): self.offset = offset; return self
        def execute(self):
            assert self.filters["user_id"] == "owner"
            assert self.filters["id" if self.name == "subjects" else "subject_id"] == "s"
            pages.append((self.name, self.offset))
            return SimpleNamespace(data=data.get(self.name, [])[self.offset:self.offset + 1000])
    monkeypatch.setattr(recommendation_service, "get_supabase_client", lambda: SimpleNamespace(table=Query))
    monkeypatch.setattr(recommendation_service, "get_subject", lambda **_: None)
    result = recommendation_service.next_actions(user_id="owner", subject_id="s")
    assert ("knowledge_points", 1000) in pages
    assert len(result["actions"]) == 3
