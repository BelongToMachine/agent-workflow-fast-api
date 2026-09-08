import math

import httpx

from app.core.config import Settings, get_settings

EMBEDDING_DIMENSIONS = 1536
EMBEDDING_BATCH_SIZE = 128


class EmbeddingConfigurationError(Exception):
    """Raised when the embedding provider is not configured safely."""


class EmbeddingProviderError(Exception):
    """Raised when the embedding provider cannot return valid vectors."""


async def embed_texts(
    texts: list[str],
    settings: Settings | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    current_settings = settings or get_settings()
    if not current_settings.embedding_api_key:
        raise EmbeddingConfigurationError(
            "EMBEDDING_API_KEY is required when knowledge embeddings are enabled."
        )

    vectors: list[list[float]] = []
    try:
        async with httpx.AsyncClient(
            timeout=current_settings.embedding_provider_timeout_seconds
        ) as client:
            for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
                batch = texts[start:start + EMBEDDING_BATCH_SIZE]
                response = await client.post(
                    f"{current_settings.embedding_base_url.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {current_settings.embedding_api_key}"},
                    json={"input": batch, "model": current_settings.embedding_model},
                )
                response.raise_for_status()
                vectors.extend(_parse_vectors(response.json(), len(batch)))
    except (httpx.HTTPError, ValueError) as error:
        raise EmbeddingProviderError("The embedding provider request failed.") from error
    return vectors


def _parse_vectors(payload: object, expected_count: int) -> list[list[float]]:
    raw_data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_data, list) or len(raw_data) != expected_count:
        raise EmbeddingProviderError("The embedding provider returned an invalid vector count.")

    indexed_vectors: dict[int, list[float]] = {}
    for item in raw_data:
        if not isinstance(item, dict):
            raise EmbeddingProviderError("The embedding provider returned invalid vector data.")
        index = item.get("index")
        if (
            type(index) is not int
            or not 0 <= index < expected_count
            or index in indexed_vectors
        ):
            raise EmbeddingProviderError("The embedding provider returned invalid vector indexes.")
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list) or len(raw_vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingProviderError(
                f"Expected {EMBEDDING_DIMENSIONS}-dimensional embeddings."
            )
        if any(type(value) not in {int, float} for value in raw_vector):
            raise EmbeddingProviderError("The embedding provider returned a non-numeric vector.")
        try:
            vector = [float(value) for value in raw_vector]
        except (ValueError, OverflowError) as error:
            raise EmbeddingProviderError(
                "The embedding provider returned an invalid vector."
            ) from error
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingProviderError("The embedding provider returned a non-finite vector.")
        indexed_vectors[index] = vector

    return [indexed_vectors[index] for index in range(expected_count)]


def vector_literal(vector: list[float]) -> str:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Expected {EMBEDDING_DIMENSIONS}-dimensional embeddings.")
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"
