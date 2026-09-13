import asyncio

import pytest
from fastapi import HTTPException

from app.models.dayend import DayendRunRequest
from app.services import dayend_run_service


class _Snapshot:
    def __init__(self, values, next_nodes=()):
        self.values = values
        self.next = next_nodes


class _Graph:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.resume_value = None

    async def aget_state(self, _config):
        return self.snapshot

    async def ainvoke(self, value, _config):
        self.resume_value = value
        return {"thread_id": "thread-1", "user_id": "student-1"}


def test_get_run_hides_another_users_thread(monkeypatch):
    graph = _Graph(_Snapshot({"user_id": "student-1"}))

    async def build():
        return graph

    monkeypatch.setattr(dayend_run_service, "build_persistent_closure_graph", build)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dayend_run_service.get_run(thread_id="thread-1", user_id="student-2"))
    assert error.value.status_code == 404


def test_resume_requires_owned_interrupted_thread(monkeypatch):
    graph = _Graph(_Snapshot({"user_id": "student-1"}, ("human_confirmation",)))

    async def build():
        return graph

    monkeypatch.setattr(dayend_run_service, "build_persistent_closure_graph", build)
    result = asyncio.run(dayend_run_service.resume_run(
        thread_id="thread-1", user_id="student-1", response={"confirmed": True},
    ))
    assert result["threadId"] == "thread-1"
    assert graph.resume_value is not None


def test_resume_rejects_completed_thread(monkeypatch):
    graph = _Graph(_Snapshot({"user_id": "student-1"}))

    async def build():
        return graph

    monkeypatch.setattr(dayend_run_service, "build_persistent_closure_graph", build)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dayend_run_service.resume_run(thread_id="thread-1", user_id="student-1", response={}))
    assert error.value.status_code == 409


def test_stream_does_not_report_completion_while_waiting_for_confirmation(monkeypatch):
    class _InterruptGraph:
        async def astream(self, *_args, **_kwargs):
            yield {"__interrupt__": (type("Interrupt", (), {"value": {"items": ["c1"]}})(),)}

    async def build():
        return _InterruptGraph()

    async def collect():
        return [item async for item in dayend_run_service.stream_run(
            request=DayendRunRequest(userInput="Need confirmation"), user_id="student-1",
        )]

    monkeypatch.setattr(dayend_run_service, "build_persistent_closure_graph", build)
    events = asyncio.run(collect())
    assert [item["event"] for item in events] == ["run_started", "confirmation_required"]
