"""Offline quality-gate validation; online cases are run by e2e_acceptance.py."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.router_agent import _fallback
from app.services.quality_eval_service import evaluate_retrieval_cases, validate_generation_case


def main() -> int:
    failures = []
    intent_cases = json.loads((ROOT / "evals" / "intent_cases.json").read_text(encoding="utf-8"))
    for case in intent_cases:
        actual = _fallback(case["input"]).primary_intent
        if actual != case["expected"]:
            failures.append(f"intent: {case['input']} expected={case['expected']} actual={actual}")
        expected_secondary = case.get("expectedSecondary")
        if expected_secondary and expected_secondary not in _fallback(case["input"]).secondary_intents:
            failures.append(f"secondary intent: {case['input']} missing={expected_secondary}")
        if case.get("needsClarification") is not None and _fallback(case["input"]).needs_clarification != case["needsClarification"]:
            failures.append(f"clarification: {case['input']}")
    retrieval_cases = json.loads((ROOT / "evals" / "retrieval_cases.json").read_text(encoding="utf-8"))
    try:
        metrics = evaluate_retrieval_cases(retrieval_cases)
        thresholds = {
            "recallAtK": 0.8, "mrr": 0.7, "citationPrecision": 0.7,
            "citationHitRate": 0.9, "modalityRecall": 0.8, "isolationRate": 1.0,
        }
        metric_values = metrics.as_dict()
        for name, threshold in thresholds.items():
            if float(metric_values[name]) < threshold:
                failures.append(f"retrieval {name}={metric_values[name]:.3f} below {threshold:.3f}")
    except ValueError as exc:
        failures.append(f"retrieval fixture: {exc}")
        metrics = None
    generation_cases = json.loads((ROOT / "evals" / "generation_cases.json").read_text(encoding="utf-8"))
    for case in generation_cases:
        failures.extend(
            f"{case.get('capability')}: {failure}"
            for failure in validate_generation_case(case)
        )
    if failures:
        print("QUALITY GATE FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    metric_summary = " ".join(
        f"{key}={value:.3f}" for key, value in (metrics.as_dict() if metrics else {}).items()
        if key != "caseCount"
    )
    print(
        f"QUALITY GATE PASSED: {len(intent_cases)} intent cases, "
        f"{len(retrieval_cases)} retrieval cases, {len(generation_cases)} generation cases; "
        f"{metric_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
