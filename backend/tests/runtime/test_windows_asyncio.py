import asyncio

from app.runtime import windows_asyncio


def test_postgres_on_windows_uses_selector_event_loop(monkeypatch):
    configured = []

    class SelectorPolicy:
        pass

    monkeypatch.setattr(windows_asyncio.sys, "platform", "win32")
    monkeypatch.setenv("DAYEND_PERSISTENCE_BACKEND", "postgres")
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", SelectorPolicy, raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", configured.append)

    windows_asyncio.configure_event_loop_policy()

    assert len(configured) == 1
    assert isinstance(configured[0], SelectorPolicy)


def test_sqlite_does_not_change_event_loop_policy(monkeypatch):
    monkeypatch.setattr(windows_asyncio.sys, "platform", "win32")
    monkeypatch.setenv("DAYEND_PERSISTENCE_BACKEND", "sqlite")
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda _: (_ for _ in ()).throw(AssertionError()))

    windows_asyncio.configure_event_loop_policy()
