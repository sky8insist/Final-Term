from app.guardrails.safety import detect_urgent_signal


def test_deterministic_guard_only_flags_explicit_urgent_signals():
    assert detect_urgent_signal("我今天很累") == {"urgent_signal": False, "matched_patterns": []}
    assert detect_urgent_signal("我不想活了") ["urgent_signal"] is True
