"""Export blinded, de-duplicated Dayend outputs for independent reviewers."""
import argparse
import json
from pathlib import Path


def latest_success(rows):
    result = {}
    for row in rows:
        if row.get("status") != "failed":
            result[(row["case_id"], row["variant"])] = row
    return list(result.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path); parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--key-dir", type=Path, required=True,
                        help="Private answer-key directory; never distribute this to reviewers.")
    args = parser.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True); args.key_dir.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
    successes = latest_success(rows)
    for reviewer in ("reviewer_a", "reviewer_b"):
        packet, answer_key = [], []
        for index, row in enumerate(successes, 1):
            review_id = f"{reviewer}-{index:03d}"
            packet.append({"review_id": review_id, "reviewer_id": reviewer,
                           "case_id": row["case_id"], "outputs": row.get("outputs", {}),
                           "grounding": None, "unsupported_task_rate": None, "actionability": None,
                           "notes": None})
            answer_key.append({"review_id": review_id, "case_id": row["case_id"], "variant": row["variant"]})
        (args.output_dir / f"{reviewer}.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.key_dir / f"{reviewer}.json").write_text(json.dumps(answer_key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
