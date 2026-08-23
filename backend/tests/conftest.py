import pytest

from app.config.settings import settings
from app.providers.openai_compatible import get_model_provider


@pytest.fixture(autouse=True)
def disable_external_mock_by_default(monkeypatch):
    """Existing unit tests explicitly control their provider responses."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "enable_wikipedia_fallback", False)
    get_model_provider.cache_clear()
    yield
    get_model_provider.cache_clear()
