from uuid import uuid4

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.main import app
from app.models.exam_goal import ExamEventSave, SyllabusCreate


def test_goals_require_authentication():
    assert TestClient(app).get(f"/api/v1/courses/{uuid4()}/exam-goals").status_code == 401


def test_exam_scope_has_stable_ids_and_unique_topics():
    topic_id = str(uuid4())
    values = {"title": "期末", "exam_date": "2026-10-10",
              "topics": [{"knowledge_point_id": topic_id, "weight": 5}]}
    assert ExamEventSave(**values).model_dump(mode="json")["topics"][0]["knowledge_point_id"] == topic_id
    for topics in [[], values["topics"] * 2, [{"knowledge_point_id": topic_id, "weight": 0}],
                   [{"knowledge_point_id": topic_id, "weight": float("nan")}]]:
        with pytest.raises(ValidationError): ExamEventSave(**{**values, "topics": topics})


def test_syllabus_requires_nonempty_unique_topic_ids():
    topic_id = str(uuid4())
    for topic_ids in [[], [topic_id, topic_id]]:
        with pytest.raises(ValidationError):
            SyllabusCreate(title="大纲", topic_ids=topic_ids)
