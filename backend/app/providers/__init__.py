"""Replaceable integrations for external model providers."""

from app.providers.openai_compatible import OpenAICompatibleProvider, get_model_provider

__all__ = ["OpenAICompatibleProvider", "get_model_provider"]
