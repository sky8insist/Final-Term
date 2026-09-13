"""Validate independent human score records before they affect a report."""
import argparse
import json
from pathlib import Path


FIELDS = ("grounding", "unsupported_task_rate", "actionability")


def validate(rows: list[dict]) -> None:
    seen = set()
    for row in rows:
        key = (row.get("case_id"), row.get("variant"), row.get("reviewer_id"))
        if not all(key) or key in seen:
            raise ValueError("scores require a unique case, variant and reviewer")
        seen.add(key)
        if any(not isinstance(row.get(field), int) or row[field] not in {0, 1, 2} for field in FIELDS):
            raise ValueError("all rubric scores must be integers from 0 to 2")


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("scores", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.scores.read_text(encoding="utf-8").splitlines() if line.strip()]
    validate(rows); print(f"valid={len(rows)}")


if __name__ == "__main__": main()
