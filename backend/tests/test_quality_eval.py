import pytest

from app.services.quality_eval_service import evaluate_retrieval_cases, validate_generation_case


def test_retrieval_metrics_measure_rank_precision_modality_and_isolation():
    metrics = evaluate_retrieval_cases([{
        "relevantIds": ["a", "b"], "forbiddenIds": ["private"],
        "expectedBlockTypes": ["table"],
        "retrieved": [
            {"id": "noise", "blockType": "paragraph"},
            {"id": "a", "blockType": "table"},
        ],
    }])

    assert metrics.recall_at_k == 0.5
    assert metrics.mrr == 0.5
    assert metrics.citation_precision == 0.5
    assert metrics.citation_hit_rate == 1.0
    assert metrics.modality_recall == 1.0
    assert metrics.isolation_rate == 1.0


def test_retrieval_metrics_reject_unlabeled_cases():
    with pytest.raises(ValueError, match="relevantIds"):
        evaluate_retrieval_cases([{"retrieved": []}])


def test_generation_validation_detects_fake_citation_and_unstable_grading():
    qa_failures = validate_generation_case({
        "capability": "qa",
        "sample": {
            "answer": "answer", "contextAvailable": True,
            "allowedCitationIds": ["real"],
            "citations": [{"id": "fake", "sourceName": "fake.pdf"}],
        },
    })
    grading_failures = validate_generation_case({
        "capability": "grading",
        "sample": {
            "repeatScores": [1, 9], "maxScore": 10, "maxStdDev": 0.5,
            "rubricBound": True, "feedback": "feedback",
        },
    })

    assert "answer contains an invented citation" in qa_failures
    assert "grading repeatability exceeds threshold" in grading_failures
