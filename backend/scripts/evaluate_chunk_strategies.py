"""Offline, shared lexical comparator for annotated complete evidence units.

This is a deterministic chunk regression fixture, not a live vector/RRF recall
experiment. Real index comparisons use evaluate_live_retrieval.py and gold blocks.
"""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chunk_service import build_block_chunk_records, build_structure_chunk_bundle
from app.services.reranker_service import LexicalReranker


def materialize(case):
    blocks = []
    for i, row in enumerate(case["blocks"]):
        text = row.get("prefix", "") + row["text"] * row.get("repeat", 1) + row.get("suffix", "")
        if row.get("joinPrevious"):
            blocks[-1]["content_text"] += text; continue
        blocks.append({"id": str(uuid5(NAMESPACE_URL, f"chunk-eval:{case['id']}:{i}")),
            "content_text": text, "block_type": row["type"], "sequence_index": i,
            "structured_data": {"rows": row["rows"]} if row.get("rows") else {}})
    return blocks


def evaluate(cases):
    reports = {}
    for strategy in ["baseline", "structure"]:
        samples = []
        for case in cases:
            started = perf_counter(); blocks = materialize(case)
            records = build_block_chunk_records(blocks) if strategy == "baseline" else build_structure_chunk_bundle(blocks)["records"]
            ranked = LexicalReranker().rank(case["query"], [{"id": str(row["chunk_index"]), "chunkText": row["content"], "rrfScore": 0.01} for row in records])[:5]
            hit = next((i for i, row in enumerate(ranked, 1) if all(phrase in row["chunkText"] for phrase in case["requiredPhrases"])), None)
            samples.append({"id": case["id"], "completeEvidenceHitAt5": int(hit is not None),
                "completeEvidenceReciprocalRank": 1 / hit if hit else 0, "chunkCount": len(records),
                "latencyMs": round((perf_counter() - started) * 1000, 3)})
        reports[strategy] = {"completeEvidenceHitAt5": sum(row["completeEvidenceHitAt5"] for row in samples) / len(samples),
            "completeEvidenceMRR": sum(row["completeEvidenceReciprocalRank"] for row in samples) / len(samples), "cases": samples}
    return {"datasetKind": "offline-chunk-regression", "retriever": "shared-lexical", "caseCount": len(cases), "strategies": reports}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "evals/chunk_quality_cases.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(); cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not cases or any(not case.get("requiredPhrases") for case in cases): raise SystemExit("Cases must contain gold evidence phrases")
    report = evaluate(cases); output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output: args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    if report["strategies"]["structure"]["completeEvidenceHitAt5"] < report["strategies"]["baseline"]["completeEvidenceHitAt5"]:
        raise SystemExit("Structural strategy regressed on the labelled fixtures")


if __name__ == "__main__": main()
