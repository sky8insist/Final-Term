import sys

import pytest

from experiments.mineru_ab import runner


def test_unknown_case_is_rejected_before_any_provider_call(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["runner", "baseline", "--case", "missing-case"])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2

