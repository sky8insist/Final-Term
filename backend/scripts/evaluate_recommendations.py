"""Run labelled, fixed-time recommendation regressions without DB/model calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.recommendation_eval_service import evaluate_recommendation_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "evals/recommendation_cases.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_recommendation_cases(json.loads(args.cases.read_text(encoding="utf-8")))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "metrics": report["metrics"]}, indent=2))
    for case in report["cases"]:
        if case["failures"]:
            print(f"FAILED {case['caseId']}: {case['failures']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
