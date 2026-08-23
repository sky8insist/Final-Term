from functools import lru_cache

import httpx

from app.config.settings import settings


class ProviderConfigurationError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    """Transport adapter shared by chat, vision and embedding services."""

    name = "openai-compatible"

    def __init__(self, *, base_url: str, api_key: str | None, trust_env: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.trust_env = trust_env

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderConfigurationError("Model provider API key is not configured")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def post_json_async(self, path: str, payload: dict, *, timeout: float = 120) -> dict:
        async with httpx.AsyncClient(timeout=timeout, trust_env=self.trust_env) as client:
            response = await client.post(f"{self.base_url}/{path.lstrip('/')}", headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()

    def post_json(self, path: str, payload: dict, *, timeout: float = 60) -> dict:
        with httpx.Client(timeout=timeout, trust_env=self.trust_env) as client:
            response = client.post(f"{self.base_url}/{path.lstrip('/')}", headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()


@lru_cache
def get_model_provider() -> OpenAICompatibleProvider:
    if settings.model_provider != "openai_compatible":
        raise ProviderConfigurationError(f"Unsupported model provider: {settings.model_provider}")
    return OpenAICompatibleProvider(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        trust_env=settings.model_provider_trust_env,
    )
