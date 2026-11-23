"""Evaluate a running API against a labeled retrieval manifest.

Manifest cases use the same schema as evals/retrieval_cases.json but omit
`retrieved`; this runner calls the real retrieval endpoint and fills it.
"""
import argparse
import json
from pathlib import Path
import sys
import os
from time import perf_counter
from statistics import quantiles
from copy import deepcopy

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.quality_eval_service import evaluate_retrieval_cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--token", default=os.environ.get("EXAMAI_EVAL_TOKEN"))
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--compare", action="store_true", help="Run baseline and adaptive on the same labels")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.token: parser.error("Set EXAMAI_EVAL_TOKEN or provide --token")
    cases = json.loads(args.manifest.read_text(encoding="utf-8"))
    evaluate_retrieval_cases([{**case, "retrieved": []} for case in cases])
    headers = {"Authorization": f"Bearer {args.token}"}
    reports = {}
    with httpx.Client(base_url=args.api_url.rstrip("/"), headers=headers, timeout=60, trust_env=False) as client:
        for strategy in (["baseline", "adaptive"] if args.compare else ["adaptive"]):
            samples = deepcopy(cases); timings = []; recall5 = []; pipelines = []
            for case in samples:
                started = perf_counter()
                response = client.post("/api/v1/retrieval/search", json={
                    "subjectId": case.get("subjectId", args.subject_id), "question": case["query"], "topK": args.top_k,
                    "blockTypes": case.get("expectedBlockTypes"), "strategy": strategy,
                    "materialIds": case.get("materialIds"),
                })
                response.raise_for_status(); timings.append((perf_counter() - started) * 1000)
                result = response.json(); pipelines.append(result.get("retrieval", {}))
                case["retrieved"] = [{"id": item.get("blockId") or item["id"], "chunkId": item.get("chunkId"), "blockType": item.get("blockType")} for item in result.get("citations", [])]
                relevant = set(case["relevantIds"])
                recall5.append(len(relevant.intersection(item["id"] for item in case["retrieved"][:5])) / len(relevant))
            metrics = evaluate_retrieval_cases(samples).as_dict()
            metrics.update(recallAt5=sum(recall5) / len(recall5),
                latencyP95Ms=quantiles(timings, n=100, method="inclusive")[94] if len(timings) > 1 else timings[0])
            reports[strategy] = {"metrics": metrics, "pipelines": pipelines, "cases": samples}
    output = json.dumps(reports, ensure_ascii=False, indent=2)
    if args.output: args.output.write_text(output + "\n", encoding="utf-8")
    print(json.dumps({name: report["metrics"] for name, report in reports.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
