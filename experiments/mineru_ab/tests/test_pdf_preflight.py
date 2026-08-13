from pathlib import Path

from experiments.mineru_ab.generate_fixtures import generate
from experiments.mineru_ab.pdf_preflight import inspect_pdf_text_layer
from experiments.mineru_ab.config import EXPERIMENT_ROOT


def test_pdf_preflight_accepts_text_and_rejects_scanned_fixture():
    generate()
    generated = EXPERIMENT_ROOT / "fixtures" / "generated"
    text_result = inspect_pdf_text_layer(generated / "simple_text.pdf")
    scan_result = inspect_pdf_text_layer(generated / "scanned_no_text.pdf")
    assert text_result.accepted is True
    assert scan_result.accepted is False
    assert scan_result.reason == "ocr_required"

