from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

from experiments.mineru_ab.config import EXPERIMENT_ROOT, ExperimentSettings
from experiments.mineru_ab.metrics import character_recall, normalize_text
from experiments.mineru_ab.models import ParseRun
from experiments.mineru_ab.runner import _load_cases, reuse_mineru, run_baseline


def _by_page(run: ParseRun) -> dict[int, str]:
    pages: dict[int, list[str]] = defaultdict(list)
    for block in run.blocks:
        if block.page is not None:
            pages[int(block.page)].append(block.text)
    return {page: "\n".join(texts) for page, texts in pages.items()}


def _stats(run: ParseRun) -> dict:
    type_blocks = Counter(block.type for block in run.blocks)
    type_chars = Counter()
    fingerprints = []
    lengths = []
    for block in run.blocks:
        normalized = normalize_text(block.text)
        type_chars[block.type] += len(normalized)
        lengths.append(len(normalized))
        fingerprints.append(sha256(normalized.encode("utf-8")).hexdigest())
    return {
        "blocksByType": dict(type_blocks),
        "charactersByType": dict(type_chars),
        "exactDuplicateBlocks": len(fingerprints) - len(set(fingerprints)),
        "maxBlockCharacters": max(lengths, default=0),
        "totalCharacters": sum(lengths),
    }


def _non_visual_text(run: ParseRun) -> str:
    return "\n".join(
        block.text for block in run.blocks if block.type not in {"image", "chart"}
    )


def diagnose(manifest: Path, summary: Path, output: Path) -> dict:
    cases = _load_cases(manifest.resolve())
    previous = json.loads(summary.read_text(encoding="utf-8"))
    baseline_runs = run_baseline(cases)
    mineru_runs = reuse_mineru(cases, ExperimentSettings.from_env(), previous)
    baseline = {run.case_id: run for run in baseline_runs}
    mineru = {run.case_id: run for run in mineru_runs}
    rows = []
    for case in cases:
        a = baseline[case["id"]]
        b = mineru[case["id"]]
        a_pages, b_pages = _by_page(a), _by_page(b)
        page_numbers = sorted(set(a_pages) | set(b_pages))
        rows.append({
            "caseId": case["id"],
            "label": case.get("label", case["id"]),
            "expectedOutcome": case.get("expected_outcome"),
            "baseline": _stats(a),
            "mineru": _stats(b),
            "baselineNonVisualCoveredByMinerU": round(
                character_recall("\n".join(block.text for block in b.blocks), _non_visual_text(a)), 4,
            ) if a.success and b.success else 0.0,
            "pages": [{
                "page": page,
                "baselineCharacters": len(normalize_text(a_pages.get(page, ""))),
                "mineruCharacters": len(normalize_text(b_pages.get(page, ""))),
                "baselineCoveredByMinerU": round(
                    character_recall(b_pages.get(page, ""), a_pages.get(page, "")), 4,
                ) if a.success and b.success else 0.0,
                "mineruCoveredByBaseline": round(
                    character_recall(a_pages.get(page, ""), b_pages.get(page, "")), 4,
                ) if a.success and b.success else 0.0,
            } for page in page_numbers],
        })
    payload = {"containsRawText": False, "cases": rows}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Create aggregate diagnostics without emitting document text")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=EXPERIMENT_ROOT / "results" / "summary.json")
    parser.add_argument("--output", type=Path, default=EXPERIMENT_ROOT / "results" / "diagnostics.json")
    args = parser.parse_args()
    result = diagnose(args.manifest, args.summary, args.output)
    print(json.dumps({"cases": len(result["cases"]), "output": str(args.output.resolve()),
                      "containsRawText": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
