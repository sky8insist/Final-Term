from __future__ import annotations

import re


def _tokens(text: str) -> set[str]:
    latin = re.findall(r"[a-zA-Z0-9_]{2,}", text.casefold())
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chinese[index:index + 2]) for index in range(len(chinese) - 1)]
    return set(latin + bigrams)


def assess_material_evidence(*, question: str, raw_context: str, citations: list[dict]) -> dict:
    if not raw_context.strip() or not citations:
        return {
            "sufficient": False, "relevance": 0.0, "coverage": 0.0,
            "reason": "empty_material_evidence",
        }
    question_tokens = _tokens(question)
    evidence_tokens = _tokens("\n".join(str(item.get("chunkText") or item.get("text") or "") for item in citations))
    overlap = len(question_tokens & evidence_tokens) / max(len(question_tokens), 1)
    useful_text = sum(len(str(item.get("chunkText") or item.get("text") or "").strip()) for item in citations)
    scores = [float(item["score"]) for item in citations if item.get("score") is not None]
    # Retrieval providers expose scores on different scales. A present citation
    # remains usable by default; only reject empty evidence or uniformly tiny
    # normalized scores that also have no lexical support.
    low_scored = bool(scores) and max(scores) < 0.2 and overlap < 0.02
    sufficient = useful_text > 0 and not low_scored
    return {
        "sufficient": sufficient,
        "relevance": round(overlap, 4),
        "coverage": min(round(useful_text / 1200, 4), 1.0),
        "reason": "material_supported" if sufficient else "weak_material_evidence",
    }
