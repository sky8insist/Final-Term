import httpx

from app.config.settings import settings


class LLMServiceError(RuntimeError):
    pass


async def generate_text_async(prompt: str, system_prompt: str | None = None, **kwargs) -> str:
    if not settings.openai_api_key:
        raise LLMServiceError("LLM API key is not configured")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": kwargs.get("temperature", 0),
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise LLMServiceError("LLM API request failed") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMServiceError("LLM response format was invalid") from exc

    if not isinstance(content, str):
        raise LLMServiceError("LLM response format was invalid")
    return content


def generate_text(prompt: str, system_prompt: str | None = None) -> str:
    raise LLMServiceError("Synchronous LLM generation is not available")
