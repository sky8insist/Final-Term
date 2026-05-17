import httpx

from app.config.settings import settings

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
    if not settings.openai_api_key:
        raise EmbeddingError("Embedding API key is not configured")

    vectors: list[list[float]] = []
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=60) as client:
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                response = client.post(
                    _embedding_url(),
                    headers=headers,
                    json={
                        "model": settings.embedding_model,
                        "input": batch,
                    },
                )
                response.raise_for_status()
                vectors.extend(_parse_embedding_response(response.json(), len(batch)))
    except httpx.HTTPStatusError as exc:
        raise EmbeddingError("Embedding API request failed") from exc
    except httpx.HTTPError as exc:
        raise EmbeddingError("Embedding API request failed") from exc

    _validate_vectors(vectors, len(texts))
    return vectors
