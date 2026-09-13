"""Startup compatibility for psycopg's async PostgreSQL connections on Windows."""

import asyncio
import os
import sys


def configure_event_loop_policy() -> None:
    """Select the loop implementation supported by psycopg before the server starts.

    psycopg async connections do not support Windows' default Proactor event
    loop.  The policy must be set before Uvicorn creates its serving loop.
    SQLite deployments intentionally retain Python's default policy.
    """
    if sys.platform != "win32" or os.getenv("DAYEND_PERSISTENCE_BACKEND", "sqlite").lower() != "postgres":
        return
    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is not None:
        asyncio.set_event_loop_policy(policy())
