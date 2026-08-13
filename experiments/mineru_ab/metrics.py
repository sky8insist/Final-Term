from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from html import unescape

from experiments.mineru_ab.models import ParseRun


def normalize_text(text: str) -> str:
    cleaned = unescape(text)
    cleaned = re.sub(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^>]*)?/?>", " ", cleaned)
    cleaned = re.sub(r"[*_`#]+", "", cleaned)
    return re.sub(r"\s+", "", cleaned).casefold()


def joined_text(run: ParseRun) -> str:
    return "\n".join(block.text for block in run.blocks)


def character_recall(actual: str, expected: str) -> float:
    actual_counter = Counter(normalize_text(actual))
    expected_counter = Counter(normalize_text(expected))
    denominator = sum(expected_counter.values())
    if denominator == 0:
        return 1.0
    overlap = sum(min(actual_counter[key], count) for key, count in expected_counter.items())
    return overlap / denominator


def evaluate_run(run: ParseRun, case: dict) -> dict:
    text = joined_text(run)
    expected = str(case.get("expected_text", ""))
    counts = Counter(block.type for block in run.blocks)
    pages = {block.page for block in run.blocks if block.page is not None}
    expected_outcome = case.get("expected_outcome", "success")
    expected_satisfied = (
        run.success if expected_outcome == "success"
        else (not run.success and run.error_code == expected_outcome)
    )
    return {
        "caseId": run.case_id,
        "provider": run.provider,
        "success": run.success,
        "durationSeconds": round(run.duration_seconds, 4),
        "characters": len(normalize_text(text)),
        "blocks": len(run.blocks),
        "headings": counts["heading"],
        "tables": counts["table"],
        "formulas": counts["formula"],
        "pagesAttributed": len(pages),
        "characterRecall": round(character_recall(text, expected), 4) if run.success else 0.0,
        "textSimilarity": round(SequenceMatcher(None, normalize_text(expected), normalize_text(text)).ratio(), 4)
        if run.success and expected else 0.0,
        "expectedOutcome": expected_outcome,
        "expectedSatisfied": expected_satisfied,
        "errorCode": run.error_code,
    }


def compare_pair(a: dict, b: dict) -> dict:
    return {
        "caseId": a["caseId"],
        "baselineSuccess": a["success"],
        "mineruSuccess": b["success"],
        "characterRecallDelta": round(b["characterRecall"] - a["characterRecall"], 4),
        "textSimilarityDelta": round(b["textSimilarity"] - a["textSimilarity"], 4),
        "headingDelta": b["headings"] - a["headings"],
        "tableDelta": b["tables"] - a["tables"],
        "formulaDelta": b["formulas"] - a["formulas"],
        "latencyDeltaSeconds": round(b["durationSeconds"] - a["durationSeconds"], 4),
    }


def compare_runs(baseline: ParseRun, mineru: ParseRun) -> dict:
    baseline_text = joined_text(baseline)
    mineru_text = joined_text(mineru)
    baseline_counts = Counter(block.type for block in baseline.blocks)
    mineru_counts = Counter(block.type for block in mineru.blocks)
    return {
        "caseId": baseline.case_id,
        "baselineSuccess": baseline.success,
        "mineruSuccess": mineru.success,
        "baselineCoveredByMinerU": round(character_recall(mineru_text, baseline_text), 4)
        if baseline.success and mineru.success else 0.0,
        "mineruCoveredByBaseline": round(character_recall(baseline_text, mineru_text), 4)
        if baseline.success and mineru.success else 0.0,
        "pairedTextSimilarity": round(
            SequenceMatcher(None, normalize_text(baseline_text), normalize_text(mineru_text)).ratio(), 4,
        ) if baseline.success and mineru.success else 0.0,
        "headingDelta": mineru_counts["heading"] - baseline_counts["heading"],
        "tableDelta": mineru_counts["table"] - baseline_counts["table"],
        "formulaDelta": mineru_counts["formula"] - baseline_counts["formula"],
        "latencyDeltaSeconds": round(mineru.duration_seconds - baseline.duration_seconds, 4),
    }
