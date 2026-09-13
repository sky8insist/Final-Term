import asyncio
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.config.settings import settings


_checkpointer: AsyncSqliteSaver | object | None = None
_postgres_context = None
_checkpointer_lock = asyncio.Lock()
DAYEND_CHECKPOINT_SERDE = JsonPlusSerializer(allowed_msgpack_modules=[
    ("app.schemas.common", "AgentEnvelope[TypeVar]"),
    ("app.schemas.common", "AgentTrace"),
])


async def get_dayend_checkpointer():
    """Return the async saver required by LangGraph's async execution APIs."""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    async with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer
        if settings.dayend_persistence_backend == "postgres":
            if not settings.database_url:
                raise RuntimeError("DAYEND_PERSISTENCE_BACKEND=postgres requires DATABASE_URL")
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            global _postgres_context
            _postgres_context = AsyncPostgresSaver.from_conn_string(
                settings.database_url, serde=DAYEND_CHECKPOINT_SERDE,
            )
            _checkpointer = await _postgres_context.__aenter__()
            await _checkpointer.setup()
        else:
            _checkpointer = AsyncSqliteSaver(
                await aiosqlite.connect(_path()), serde=DAYEND_CHECKPOINT_SERDE,
            )
        return _checkpointer


def _path() -> Path:
    path = Path(settings.dayend_checkpoint_path)
    if not path.is_absolute():
        path = Path.cwd().parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
