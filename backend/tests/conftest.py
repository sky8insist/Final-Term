import pytest
from contextlib import nullcontext
from types import SimpleNamespace

from app.config.settings import settings
from app.providers.openai_compatible import get_model_provider


@pytest.fixture(autouse=True)
def disable_external_mock_by_default(monkeypatch):
    """Existing unit tests explicitly control their provider responses."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "enable_wikipedia_fallback", False)
    # Unit fakes do not own a live PostgreSQL connection. Real IO-lock behavior
    # is exercised by the isolated acceptance script and dedicated lock tests.
    from app.services import owner_io_service
    monkeypatch.setattr(owner_io_service, 'hold_owner_io',
                        lambda _: nullcontext(SimpleNamespace(execute=lambda *_: None)))
    get_model_provider.cache_clear()
    yield
    get_model_provider.cache_clear()
