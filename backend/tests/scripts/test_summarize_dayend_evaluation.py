import importlib.util
from pathlib import Path


def _module():
    path = Path("scripts/summarize_dayend_evaluation.py")
    spec = importlib.util.spec_from_file_location("summarize_dayend_evaluation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_summary_keeps_missing_real_metrics_as_na():
    report = _module().summarize([{
        "case_id": "closure-001", "variant": "single_agent", "simulated": False,
        "grounding": 0.8, "latency_ms": 123, "total_tokens": 456,
    }])
    row = report["variants"]["single_agent"]
    assert row["grounding"] == 0.8
    assert row["total_tokens"] == 456.0
    assert row["token_cost"] == "N/A"
    assert report["variants"]["full_multi_agent"]["cases"] == 0
