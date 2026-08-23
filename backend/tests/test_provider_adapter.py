import pytest

from app.providers.openai_compatible import OpenAICompatibleProvider, ProviderConfigurationError


def test_provider_requires_key_only_when_calling():
    provider = OpenAICompatibleProvider(base_url="https://example.invalid/v1", api_key=None)
    with pytest.raises(ProviderConfigurationError):
        _ = provider.headers


def test_provider_normalizes_base_url():
    provider = OpenAICompatibleProvider(base_url="https://example.invalid/v1/", api_key="test")
    assert provider.base_url == "https://example.invalid/v1"
    assert provider.name == "openai-compatible"
    assert provider.trust_env is False
