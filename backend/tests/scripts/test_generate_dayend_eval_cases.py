import importlib.util
from collections import Counter
from pathlib import Path


def test_synthetic_eval_corpus_has_required_distribution():
    path = Path("scripts/generate_dayend_eval_cases.py")
    spec = importlib.util.spec_from_file_location("generate_dayend_eval_cases", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    cases = module.build_cases()
    assert len(cases) == 100
    assert Counter(case["category"] for case in cases) == {
        "closure": 30, "emotion": 25, "mixed": 20, "uncertain": 10,
        "edge_conflict": 10, "safety_critical": 5,
    }
    assert {case["source"] for case in cases} == {"synthetic_fixture"}
