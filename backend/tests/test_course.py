from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.course import TopicCreate, TopicUpdate
from app.services import course_service, exam_service


class Database:
    def __init__(self, tables):
        self.tables = tables
        self.writes = []

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, db, table):
        self.db, self.name, self.filters, self.payload = db, table, {}, None

    def select(self, *args): return self
    def limit(self, *args): return self
    def order(self, *args): return self
    def eq(self, key, value):
        self.filters[key] = value
        return self
    def update(self, values):
        self.payload = values
        return self
    def insert(self, values):
        self.db.tables.setdefault(self.name, []).append(values)
        self.db.writes.append((self.name, values))
        return self
    def execute(self):
        rows = [row for row in self.db.tables.get(self.name, [])
                if all(row.get(key) == value for key, value in self.filters.items())]
        if self.payload is not None:
            for row in rows: row.update(self.payload)
            self.db.writes.append((self.name, self.payload))
        return SimpleNamespace(data=rows)


def test_course_routes_authenticate():
    client = TestClient(app)
    subject = "00000000-0000-0000-0000-000000000001"
    assert client.get(f"/api/v1/courses/{subject}/structure").status_code == 401
    assert client.post(f"/api/v1/courses/{subject}/topics", json={"title": "矩阵"}).status_code == 401


@pytest.mark.parametrize("values", [{"title": "  "}, {"title": "a", "knowledge_key": "changed"},
                                    {"title": "a", "syllabus_weight": float('nan')},
                                    {"title": "a", "sequence_index": -1}])
def test_invalid_topic_create(values):
    with pytest.raises(ValidationError): TopicCreate(**values)


def test_update_distinguishes_unset_unit_from_explicit_null():
    assert TopicUpdate(title=" Matrix ").model_dump(exclude_unset=True) == {"title": "Matrix"}
    assert TopicUpdate(unit_id=None).model_dump(exclude_unset=True) == {"unit_id": None}
    for values in ({"title": None}, {"archived": None}, {"syllabus_weight": None}):
        with pytest.raises(ValidationError): TopicUpdate(**values)


def test_rename_preserves_mastery_identity_and_old_alias(monkeypatch):
    original = {"id": "topic", "user_id": "u", "subject_id": "s", "title": "矩阵",
                "knowledge_key": "matrix-v1"}
    db = Database({"knowledge_points": [original], "topic_aliases": [
        {"user_id": "u", "subject_id": "s", "alias": "矩阵", "knowledge_point_id": "topic"}]})
    monkeypatch.setattr(course_service, "get_supabase_client", lambda: db)
    saved = course_service.update_topic(user_id="u", subject_id="s", topic_id="topic", values={"title": "矩阵基础"})
    assert saved["knowledge_key"] == "matrix-v1"
    assert {row["alias"] for row in db.tables["topic_aliases"]} == {"矩阵", "矩阵基础"}
    assert all(table not in {"knowledge_mastery", "mastery_history"} for table, _ in db.writes)


def test_cross_owner_and_cross_subject_edits_fail_without_mutation(monkeypatch):
    db = Database({"knowledge_points": [{"id": "t", "user_id": "owner", "subject_id": "s"}]})
    monkeypatch.setattr(course_service, "get_supabase_client", lambda: db)
    for user, subject in [("other", "s"), ("owner", "other")]:
        with pytest.raises(HTTPException) as caught:
            course_service.update_topic(user_id=user, subject_id=subject, topic_id="t", values={"archived": True})
        assert caught.value.status_code == 404
    assert db.writes == []


def test_rename_collision_and_foreign_unit_fail_without_mutation(monkeypatch):
    db = Database({"knowledge_points": [{"id": "t", "user_id": "u", "subject_id": "s", "title": "A"}],
                   "topic_aliases": [{"user_id": "u", "subject_id": "s", "alias": "b", "knowledge_point_id": "other"}],
                   "knowledge_units": [{"id": "unit", "user_id": "u", "subject_id": "other"}]})
    monkeypatch.setattr(course_service, "get_supabase_client", lambda: db)
    for values, code in [({"title": "B"}, 409), ({"unit_id": "unit"}, 404)]:
        with pytest.raises(HTTPException) as caught:
            course_service.update_topic(user_id="u", subject_id="s", topic_id="t", values=values)
        assert caught.value.status_code == code
    assert db.writes == []


def test_generation_resolves_alias_without_overwriting_display_name():
    calls = []
    topic = {"id": "stable-id", "title": "用户修改后的名称", "knowledge_key": "original-key"}
    class Client:
        def rpc(self, name, values):
            calls.append((name, values))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=topic))
    assert exam_service._get_or_create_knowledge_point(client=Client(), user_id="u", subject_id="s",
                                                      knowledge_key="ORIGINAL-KEY") == topic
    assert calls[0][0] == "resolve_course_topic"
