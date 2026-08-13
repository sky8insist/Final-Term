from experiments.mineru_ab.metrics import character_recall, compare_runs, evaluate_run, normalize_text
from experiments.mineru_ab.models import ExperimentBlock, ParseRun


def test_character_recall_ignores_spacing_and_case():
    assert character_recall("TCP slow\nstart", "tcp slow start") == 1.0


def test_character_metrics_ignore_html_and_markdown_wrappers():
    actual = "**Network Review** <table><tr><td>Protocol</td><td>TCP</td></tr></table>"
    expected = "Network Review Protocol TCP"
    assert character_recall(actual, expected) == 1.0
    assert normalize_text(actual) == normalize_text(expected)


def test_character_metrics_preserve_mathematical_angle_brackets():
    assert normalize_text("0 < x > -1") == "0<x>-1"


def test_evaluation_counts_structured_blocks():
    run = ParseRun(
        case_id="one", provider="baseline", success=True, duration_seconds=0.2,
        blocks=[
            ExperimentBlock("heading", "Title", 0, page=1),
            ExperimentBlock("table", "A B", 1, page=2),
        ],
    )
    result = evaluate_run(run, {"expected_text": "Title A B", "expected_outcome": "success"})
    assert result["characterRecall"] == 1.0
    assert result["headings"] == 1
    assert result["tables"] == 1
    assert result["pagesAttributed"] == 2
    assert result["expectedSatisfied"] is True


def test_expected_ocr_rejection_counts_as_satisfied():
    run = ParseRun(
        case_id="scan", provider="mineru", success=False, duration_seconds=0.01,
        error_code="ocr_required",
    )
    result = evaluate_run(run, {"expected_text": "", "expected_outcome": "ocr_required"})
    assert result["expectedSatisfied"] is True


def test_paired_comparison_does_not_require_ground_truth():
    baseline = ParseRun(
        case_id="pair", provider="baseline", success=True, duration_seconds=0.1,
        blocks=[ExperimentBlock("paragraph", "Alpha Beta", 0)],
    )
    mineru = ParseRun(
        case_id="pair", provider="mineru", success=True, duration_seconds=1.1,
        blocks=[ExperimentBlock("heading", "Alpha", 0), ExperimentBlock("paragraph", "Beta", 1)],
    )
    result = compare_runs(baseline, mineru)
    assert result["baselineCoveredByMinerU"] == 1.0
    assert result["mineruCoveredByBaseline"] == 1.0
    assert result["headingDelta"] == 1
