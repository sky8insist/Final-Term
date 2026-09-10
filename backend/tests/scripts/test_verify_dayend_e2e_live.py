import importlib.util
from pathlib import Path


def test_merge_update_keeps_prior_agent_traces():
    path = Path("scripts/verify_dayend_e2e_live.py")
    spec = importlib.util.spec_from_file_location("verify_dayend_e2e_live", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = {"agent_trace": ["critic"], "value": "old"}
    module.merge_update(state, {"agent_trace": ["planner"], "value": "new"})
    assert state == {"agent_trace": ["critic", "planner"], "value": "new"}
