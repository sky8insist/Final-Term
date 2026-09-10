import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import settings


def _path() -> Path:
    path = Path(settings.dayend_store_path)
    return path if path.is_absolute() else Path.cwd().parent / path


def _connection() -> sqlite3.Connection:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE IF NOT EXISTS dayend_runs (
        run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, user_id TEXT,
        status TEXT NOT NULL, state_json TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS dayend_night_states (
        thread_id TEXT PRIMARY KEY, user_id TEXT, closure_json TEXT,
        planning_json TEXT, emotion_json TEXT, confirmation_json TEXT,
        updated_at TEXT NOT NULL
    )""")
    return connection


def persist_validated_state(state: dict) -> None:
    """Persist business projections separately from LangGraph checkpoints."""
    def data(name: str):
        value = state.get(name)
        return getattr(value, "data", value)

    def encode(value):
        return json.dumps(value, ensure_ascii=False, default=lambda item: item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item))

    now = datetime.now(timezone.utc).isoformat()
    serialized = encode(state)
    with _connection() as connection:
        connection.execute("INSERT OR REPLACE INTO dayend_runs VALUES (?, ?, ?, ?, ?, ?)", (
            state["run_id"], state["thread_id"], state.get("user_id"), "completed", serialized, now,
        ))
        connection.execute("INSERT OR REPLACE INTO dayend_night_states VALUES (?, ?, ?, ?, ?, ?, ?)", (
            state["thread_id"], state.get("user_id"), encode(data("closure_result")),
            encode(data("planning_result")), encode(data("emotion_result")), encode(state.get("human_response")), now,
        ))


def get_night_state(thread_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT closure_json, planning_json, emotion_json, confirmation_json FROM dayend_night_states WHERE thread_id = ?", (thread_id,)).fetchone()
    if not row:
        return None
    return {"closure": json.loads(row[0]) if row[0] else None, "planning": json.loads(row[1]) if row[1] else None,
            "emotion": json.loads(row[2]) if row[2] else None, "confirmation": json.loads(row[3]) if row[3] else None}
