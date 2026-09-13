import importlib.util
from pathlib import Path
import pytest


def test_scores_require_complete_distinct_rubric_rows():
    path = Path("scripts/validate_dayend_scores.py")
    spec = importlib.util.spec_from_file_location("validate_dayend_scores", path)
    module = importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(module)
    row = {"case_id": "c1", "variant": "single_agent", "reviewer_id": "r1", "grounding": 2, "unsupported_task_rate": 1, "actionability": 2}
    module.validate([row])
    with pytest.raises(ValueError): module.validate([row, row])
