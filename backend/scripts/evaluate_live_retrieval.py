"""Evaluate a running API against a labeled retrieval manifest.

Manifest cases use the same schema as evals/retrieval_cases.json but omit
`retrieved`; this runner calls the real retrieval endpoint and fills it.
"""
import argparse
import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.quality_eval_service import evaluate_retrieval_cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    cases = json.loads(args.manifest.read_text(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(base_url=args.api_url.rstrip("/"), headers=headers, timeout=60) as client:
        for case in cases:
            response = client.post("/api/v1/retrieval/search", json={
                "subjectId": args.subject_id, "question": case["query"], "topK": args.top_k,
                "blockTypes": case.get("expectedBlockTypes"),
            })
            response.raise_for_status()
            case["retrieved"] = [
                {"id": item["id"], "blockType": item.get("blockType")}
                for item in response.json().get("citations", [])
            ]
    print(json.dumps(evaluate_retrieval_cases(cases).as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
