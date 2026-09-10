import sqlite3
from functools import lru_cache
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config.settings import settings


@lru_cache
def get_dayend_checkpointer() -> SqliteSaver:
    path = Path(settings.dayend_checkpoint_path)
    if not path.is_absolute():
        path = Path.cwd().parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
