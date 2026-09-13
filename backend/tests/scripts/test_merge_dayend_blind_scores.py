import importlib.util
from pathlib import Path

import pytest


def _module():
    spec = importlib.util.spec_from_file_location("merge_dayend_blind_scores", Path("scripts/merge_dayend_blind_scores.py"))
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(module)
    return module


def test_merge_keeps_variant_private_until_score_import():
    merged = _module().merge(
        [{"review_id": "reviewer_a-001", "reviewer_id": "reviewer_a", "grounding": 2}],
        [{"review_id": "reviewer_a-001", "case_id": "closure-001", "variant": "full_multi_agent"}],
    )
    assert merged[0]["variant"] == "full_multi_agent"


def test_merge_rejects_unknown_review_id():
    with pytest.raises(ValueError, match="unknown review_id"):
        _module().merge([{"review_id": "missing"}], [])
