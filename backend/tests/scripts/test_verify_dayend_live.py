import importlib.util
from pathlib import Path


def test_live_verifier_imports_json_for_jsonl_records():
    path = Path("scripts/verify_dayend_live.py")
    spec = importlib.util.spec_from_file_location("verify_dayend_live", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.json.dumps({"acceptance": "PASS"}) == '{"acceptance": "PASS"}'
