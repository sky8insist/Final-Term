from dataclasses import dataclass
from statistics import pstdev
from typing import Any


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_k: float
    mrr: float
    citation_precision: float
    citation_hit_rate: float
    modality_recall: float
    isolation_rate: float
    case_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "recallAtK": self.recall_at_k,
            "mrr": self.mrr,
            "citationPrecision": self.citation_precision,
            "citationHitRate": self.citation_hit_rate,
            "modalityRecall": self.modality_recall,
            "isolationRate": self.isolation_rate,
            "caseCount": self.case_count,
        }


def evaluate_retrieval_cases(cases: list[dict[str, Any]]) -> RetrievalMetrics:
    if not cases:
        raise ValueError("Retrieval evaluation requires at least one case")
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    precisions: list[float] = []
    citation_hits: list[float] = []
    modality_hits: list[float] = []
    isolation_hits: list[float] = []
    for case in cases:
        relevant = {str(value) for value in case.get("relevantIds", [])}
        if not relevant:
            raise ValueError("Every retrieval case must declare relevantIds")
        retrieved = case.get("retrieved", [])
        retrieved_ids = [str(item.get("id")) for item in retrieved]
        matched = relevant.intersection(retrieved_ids)
        recalls.append(len(matched) / len(relevant))
        first_rank = next(
            (index for index, identifier in enumerate(retrieved_ids, start=1) if identifier in relevant),
            None,
        )
        reciprocal_ranks.append(1 / first_rank if first_rank else 0.0)
        precisions.append(len(matched) / len(retrieved_ids) if retrieved_ids else 0.0)
        citation_hits.append(1.0 if matched else 0.0)
        expected_types = set(case.get("expectedBlockTypes", []))
        returned_types = {item.get("blockType") for item in retrieved if item.get("id") in relevant}
        modality_hits.append(
            len(expected_types.intersection(returned_types)) / len(expected_types)
            if expected_types else 1.0
        )
        forbidden = {str(value) for value in case.get("forbiddenIds", [])}
        isolation_hits.append(1.0 if forbidden.isdisjoint(retrieved_ids) else 0.0)
    count = len(cases)
    average = lambda values: sum(values) / count
    return RetrievalMetrics(
        recall_at_k=average(recalls),
        mrr=average(reciprocal_ranks),
        citation_precision=average(precisions),
        citation_hit_rate=average(citation_hits),
        modality_recall=average(modality_hits),
        isolation_rate=average(isolation_hits),
        case_count=count,
    )


def validate_generation_case(case: dict[str, Any]) -> list[str]:
    capability = case.get("capability")
    sample = case.get("sample") or {}
    failures: list[str] = []
    if capability == "qa":
        answer = str(sample.get("answer", "")).strip()
        citations = sample.get("citations") or []
        if not answer:
            failures.append("answer is empty")
        if sample.get("contextAvailable") and not citations:
            failures.append("grounded answer has no citations")
        if any(not item.get("id") or not item.get("sourceName") for item in citations):
            failures.append("citation identity is incomplete")
        allowed = {str(value) for value in sample.get("allowedCitationIds", [])}
        if allowed and any(str(item.get("id")) not in allowed for item in citations):
            failures.append("answer contains an invented citation")
    elif capability == "ocr":
        if not str(sample.get("text", "")).strip():
            failures.append("OCR text is empty")
        if sample.get("pageNumber") is None and sample.get("startTime") is None:
            failures.append("OCR result is not traceable")
        confidence = float(sample.get("confidence", 0))
        if confidence < 0.6 and not sample.get("needsReview"):
            failures.append("low-confidence OCR is not flagged")
    elif capability == "exam":
        questions = sample.get("questions") or []
        expected_count = int(sample.get("expectedCount", 0))
        if len(questions) != expected_count:
            failures.append("question count does not match blueprint")
        if abs(sum(float(item.get("points", 0)) for item in questions) - float(sample.get("totalPoints", 0))) > 0.001:
            failures.append("question points do not match blueprint")
        stems = [str(item.get("stem", "")).strip().casefold() for item in questions]
        if len(stems) != len(set(stems)):
            failures.append("exam contains duplicate stems")
        for item in questions:
            if item.get("correctAnswer") in (None, "", []):
                failures.append("question has no answer")
            if not item.get("citationIds"):
                failures.append("question has no citation")
    elif capability == "grading":
        scores = [float(value) for value in sample.get("repeatScores", [])]
        maximum = float(sample.get("maxScore", 0))
        if not scores:
            failures.append("grading has no repeated scores")
        elif any(score < 0 or score > maximum for score in scores):
            failures.append("grading score is outside allowed range")
        if scores and pstdev(scores) > float(sample.get("maxStdDev", 0.5)):
            failures.append("grading repeatability exceeds threshold")
        if not str(sample.get("feedback", "")).strip():
            failures.append("grading feedback is empty")
        if not sample.get("rubricBound"):
            failures.append("grading is not bound to a fixed rubric")
    else:
        failures.append(f"unsupported capability: {capability}")
    return failures
