import httpx
from time import perf_counter

from app.config.settings import settings
from app.providers.openai_compatible import ProviderConfigurationError, get_model_provider
from app.services.observability_service import ensure_model_budget, record_model_call
from app.services.mock_external_service import mock_embedding

DEFAULT_EMBEDDING_BATCH_SIZE = 32


class EmbeddingError(RuntimeError):
    pass


def _embedding_url() -> str:
    return f"{settings.openai_base_url.rstrip('/')}/embeddings"


def _validate_vectors(vectors: list[list[float]], expected_count: int) -> None:
    if len(vectors) != expected_count:
        raise EmbeddingError("Embedding response count did not match input count")

    dimensions: int | None = None
    for vector in vectors:
        if not vector:
            raise EmbeddingError("Embedding response included an empty vector")
        if dimensions is None:
            dimensions = len(vector)
        elif len(vector) != dimensions:
            raise EmbeddingError("Embedding response dimensions were inconsistent")


def _parse_embedding_response(payload: dict, expected_count: int) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise EmbeddingError("Embedding response did not include data")

    try:
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in ordered]
    except (TypeError, KeyError) as exc:
        raise EmbeddingError("Embedding response format was invalid") from exc

    if not all(isinstance(vector, list) for vector in vectors):
        raise EmbeddingError("Embedding response format was invalid")

    _validate_vectors(vectors, expected_count)
    return vectors


def embed_texts(texts: list[str], batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE) -> list[list[float]]:
    if not texts:
        return []
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")
    if settings.mock_external_apis:
        return [mock_embedding(text, settings.mock_embedding_dimensions) for text in texts]
    if not settings.openai_api_key:
        raise EmbeddingError("Embedding API key is not configured")
    ensure_model_budget()

    vectors: list[list[float]] = []
    started_at = perf_counter()
    try:
        provider = get_model_provider()
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            payload = provider.post_json(
                "embeddings", {"model": settings.embedding_model, "input": batch}, timeout=60,
            )
            vectors.extend(_parse_embedding_response(payload, len(batch)))
    except httpx.HTTPStatusError as exc:
        record_model_call(capability="embedding", model_name=settings.embedding_model,
                          status="failed", started_at=started_at, error_code="http_status")
        raise EmbeddingError("Embedding API request failed") from exc
    except (httpx.HTTPError, ProviderConfigurationError) as exc:
        record_model_call(capability="embedding", model_name=settings.embedding_model,
                          status="failed", started_at=started_at, error_code="http_error")
        raise EmbeddingError("Embedding API request failed") from exc

    _validate_vectors(vectors, len(texts))
    estimated_tokens = sum(max(len(text) // 4, 1) for text in texts)
    record_model_call(
        capability="embedding", model_name=settings.embedding_model,
        status="succeeded", started_at=started_at,
        usage={"prompt_tokens": estimated_tokens},
        metadata={"textCount": len(texts), "dimensions": len(vectors[0])},
        estimated_cost_usd=estimated_tokens * settings.embedding_cost_per_million / 1_000_000,
    )
    return vectors
