"""Summarize real Dayend A/B/C evaluation records without inventing metrics.

Input is JSONL produced by a real-provider runner. Every record must identify a
case, variant, and provider trace. Judge fields are optional; absent evidence is
reported as N/A rather than zero.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


VARIANTS = {"single_agent", "multi_agent_without_critic", "full_multi_agent"}


def summarize(records: list[dict]) -> dict:
    failures = [row for row in records if row.get("status") == "failed"]
    latest = {}
    for row in records:
        if row.get("status") != "failed":
            latest[(row.get("case_id"), row.get("variant"))] = row
    records = list(latest.values())
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("variant") not in VARIANTS:
            raise ValueError("evaluation record has an unknown variant")
        if not record.get("case_id") or record.get("simulated") is not False:
            raise ValueError("records must have a real case_id and simulated=false")
        grouped[record["variant"]].append(record)

    report = {"record_count": len(records), "failure_attempts": len(failures), "variants": {}}
    for variant in sorted(VARIANTS):
        rows = grouped[variant]
        def mean(key: str):
            values = [float(row[key]) for row in rows if row.get(key) is not None]
            return round(sum(values) / len(values), 4) if values else "N/A"
        report["variants"][variant] = {
            "cases": len(rows),
            "grounding": mean("grounding"),
            "unsupported_task_rate": mean("unsupported_task_rate"),
            "actionability": mean("actionability"),
            "latency_ms": mean("latency_ms"),
            "total_tokens": mean("total_tokens"),
            "token_cost": mean("token_cost"),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
    args.output.write_text(json.dumps(summarize(rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
