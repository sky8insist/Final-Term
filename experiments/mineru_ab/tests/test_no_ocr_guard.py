import pytest

from experiments.mineru_ab.config import ExperimentSettings
from experiments.mineru_ab.providers.mineru_provider import MinerUError, MinerUProvider


def test_non_pipeline_configuration_is_rejected():
    with pytest.raises(ValueError, match="pipeline"):
        MinerUProvider(ExperimentSettings(model_version="vlm"), test_mode=True)


def test_ocr_true_payload_is_rejected():
    payload = {
        "model_version": "pipeline",
        "files": [{"name": "scan.pdf", "data_id": "one", "is_ocr": True}],
    }
    with pytest.raises(MinerUError, match="OCR"):
        MinerUProvider.assert_no_ocr(payload)


def test_live_calls_require_explicit_switch_and_token():
    provider = MinerUProvider(ExperimentSettings(live=False, token=""))
    with pytest.raises(RuntimeError, match="disabled"):
        provider.request_upload(filename="sample.pdf", data_id="one")
    provider.close()

