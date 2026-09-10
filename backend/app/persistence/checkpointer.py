import asyncio
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.config.settings import settings


_checkpointer: AsyncSqliteSaver | None = None
_checkpointer_lock = asyncio.Lock()
DAYEND_CHECKPOINT_SERDE = JsonPlusSerializer(allowed_msgpack_modules=[
    ("app.schemas.common", "AgentEnvelope[TypeVar]"),
    ("app.schemas.common", "AgentTrace"),
])


async def get_dayend_checkpointer() -> AsyncSqliteSaver:
    """Return the async saver required by LangGraph's async execution APIs."""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    async with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer
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
