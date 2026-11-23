import asyncio
from threading import Event
from types import SimpleNamespace

import pytest

from app.config.settings import settings
from app.services import lightrag_service as graph, owner_io_service
from app.services.owner_io_service import hold_owner_io as real_hold

OWNER='00000000-0000-0000-0000-000000000001'


def index():
    return graph.index_material(user_id=OWNER,subject_id=OWNER,material_id='lifecycle',
                                filename='notes.txt',chunks=[],embedding_dimension=3)


def test_cooperative_timeout_cancels_before_late_write(monkeypatch):
    writes=[]
    stopped=Event()
    async def slow(**kw):
        try:
            await asyncio.sleep(1)
            writes.append('late')
        finally:
            stopped.set()
    monkeypatch.setattr(graph,'_index_material_async',slow)
    monkeypatch.setattr(settings,'lightrag_index_timeout_seconds',.02)
    with pytest.raises(graph.LightRAGServiceError,match='timed out'):index()
    assert stopped.wait(.5) and not writes


def test_uncancellable_io_keeps_owner_lock_until_thread_really_finishes(monkeypatch):
    entered,release,closed=Event(),Event(),Event()
    class Conn:
        def execute(self,*a):return SimpleNamespace(fetchone=lambda:[True])
        def close(self):closed.set()
    monkeypatch.setattr(owner_io_service.psycopg,'connect',lambda *a,**kw:Conn())
    async def blocking(**kw):
        entered.set()
        release.wait(2)  # Simulate a sync provider that cannot honor cancellation.
        return 'workspace'
    monkeypatch.setattr(graph,'_index_material_async',blocking)
    monkeypatch.setattr(settings,'lightrag_index_timeout_seconds',.02)
    try:
        with real_hold(OWNER):
            with pytest.raises(graph.LightRAGServiceError,match='timed out'):index()
        assert entered.is_set() and not closed.is_set()
    finally:
        release.set()
    assert closed.wait(1)


def test_timed_out_waiter_never_starts_after_global_graph_lock_releases(monkeypatch):
    writes=[]
    async def write(**kw):writes.append(True);return 'workspace'
    monkeypatch.setattr(graph,'_index_material_async',write)
    monkeypatch.setattr(settings,'lightrag_index_timeout_seconds',.02)
    with graph._RAG_ENV_LOCK:
        with pytest.raises(graph.LightRAGServiceError,match='timed out'):index()
    assert not writes


def test_pin_release_is_idempotent_and_nested_guards_close_once(monkeypatch):
    closed=[]
    class Conn:
        def execute(self,*a):return SimpleNamespace(fetchone=lambda:[True])
        def close(self):closed.append(True)
    monkeypatch.setattr(owner_io_service.psycopg,'connect',lambda *a,**kw:Conn())
    with real_hold(OWNER) as first:
        with real_hold(OWNER) as second:
            assert first is second
            release=owner_io_service.pin_owner_io(OWNER)
    assert not closed
    release();release()
    assert closed==[True]
