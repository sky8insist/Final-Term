from pathlib import Path
from uuid import uuid4

from app.persistence import store


def test_business_projection_is_separate_and_available_to_morning(monkeypatch):
    data_dir = Path("data/dayend")
    data_dir.mkdir(parents=True, exist_ok=True)
    test_db = data_dir / f"test-business-{uuid4().hex}.sqlite"
    monkeypatch.setattr(store.settings, "dayend_store_path", str(test_db))
    try:
        store.persist_validated_state({"run_id": "r", "thread_id": "t", "user_id": "u", "closure_result": {"items": []}, "planning_result": {"tomorrow_items": [{"title": "Send draft"}]}, "emotion_result": {"events": []}, "human_response": {"ok": True}})
        state = store.get_night_state("t")
        assert state["planning"]["tomorrow_items"][0]["title"] == "Send draft"
        assert state["confirmation"] == {"ok": True}
    finally:
        test_db.unlink(missing_ok=True)
