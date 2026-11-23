"""Cooperating material writers/deleters hold one nonblocking owner IO lock."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from uuid import UUID
from threading import Lock

from fastapi import HTTPException
import psycopg
from app.config.settings import settings

_held = ContextVar('material_owner_io', default=None)


class _OwnerIO:
    """Keep the transaction alive until both caller and background IO finish."""

    def __init__(self, conn):
        self.conn = conn
        self._lock = Lock()
        self._references = 1

    def pin(self):
        with self._lock:
            self._references += 1
        released = False

        def release():
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
            self.release()
        return release

    def release(self):
        with self._lock:
            self._references -= 1
            close = self._references == 0
        if close:
            self.conn.close()


def pin_owner_io(user_id: str):
    active = (_held.get() or {}).get(str(UUID(user_id)))
    return active.pin() if active else lambda: None


@contextmanager
def hold_owner_io(user_id: str):
    owner = str(UUID(user_id))
    active = _held.get() or {}
    if owner in active:
        yield active[owner].conn
        return
    conn = psycopg.connect(settings.database_url, connect_timeout=5)
    handle = _OwnerIO(conn)
    try:
        if not conn.execute("select pg_try_advisory_xact_lock(hashtextextended('material-io:'||%s,0))", (owner,)).fetchone()[0]:
            raise HTTPException(409, '资料正在处理或清理，请稍后重试')
        token = _held.set({**active, owner: handle})
        try:
            yield conn
        finally:
            _held.reset(token)
    finally:
        handle.release()


def serialized_owner(fn):
    sig = signature(fn)
    @wraps(fn)
    def wrapped(*args, **kwargs):
        owner = sig.bind(*args, **kwargs).arguments['user_id']
        with hold_owner_io(owner):
            return fn(*args, **kwargs)
    return wrapped
