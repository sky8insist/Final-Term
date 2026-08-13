import httpx
import json
from time import perf_counter
from json_repair import repair_json

from app.config.settings import settings
from app.providers.openai_compatible import ProviderConfigurationError, get_model_provider
from app.services.observability_service import ensure_model_budget, record_model_call
from app.services.mock_external_service import mock_json, mock_text


class LLMServiceError(RuntimeError):
    pass


async def generate_text_async(prompt: str, system_prompt: str | None = None, **kwargs) -> str:
    if settings.mock_external_apis:
        return mock_text(prompt)
    if not settings.openai_api_key:
        raise LLMServiceError("LLM API key is not configured")
    ensure_model_budget()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": kwargs.get("temperature", 0),
    }

    started_at = perf_counter()
    try:
        data = await get_model_provider().post_json_async("chat/completions", payload, timeout=120)
    except (httpx.HTTPError, ProviderConfigurationError) as exc:
        record_model_call(capability="chat", model_name=settings.llm_model, status="failed",
                          started_at=started_at, error_code="http_error")
        raise LLMServiceError("LLM API request failed") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMServiceError("LLM response format was invalid") from exc

    if not isinstance(content, str):
        raise LLMServiceError("LLM response format was invalid")
    record_model_call(capability="chat", model_name=settings.llm_model, status="succeeded",
                      started_at=started_at, usage=data.get("usage"))
    return content


async def generate_json_async(prompt: str, system_prompt: str | None = None, **kwargs) -> dict:
    if settings.mock_external_apis:
        return mock_json(prompt)
    content = await generate_text_async(
        prompt, system_prompt=system_prompt, temperature=kwargs.get("temperature", 0),
    )
    try:
        result = json.loads(repair_json(content))
    except (ValueError, TypeError) as exc:
        raise LLMServiceError("LLM JSON response was invalid") from exc
    if not isinstance(result, dict):
        raise LLMServiceError("LLM JSON response was invalid")
    return result


def generate_text(prompt: str, system_prompt: str | None = None) -> str:
    raise LLMServiceError("Synchronous LLM generation is not available")
