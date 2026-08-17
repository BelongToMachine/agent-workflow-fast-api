import math
from typing import Any

import httpx

from app.core.config import Settings, get_settings

EMBEDDING_DIMENSIONS = 1536


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

    body: dict[str, Any] = {
        "input": texts,
        "model": current_settings.embedding_model,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{current_settings.embedding_base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {current_settings.embedding_api_key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise EmbeddingProviderError("The embedding provider request failed.") from error

    raw_data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_data, list) or len(raw_data) != len(texts):
        raise EmbeddingProviderError("The embedding provider returned an invalid vector count.")

    ordered_data = sorted(
        (item for item in raw_data if isinstance(item, dict)),
        key=lambda item: item.get("index", 0),
    )
    if len(ordered_data) != len(texts):
        raise EmbeddingProviderError("The embedding provider returned invalid vector data.")

    vectors: list[list[float]] = []
    for item in ordered_data:
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list) or len(raw_vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingProviderError(
                f"Expected {EMBEDDING_DIMENSIONS}-dimensional embeddings."
            )
        vector = [float(value) for value in raw_vector]
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingProviderError("The embedding provider returned a non-finite vector.")
        vectors.append(vector)

    return vectors


def vector_literal(vector: list[float]) -> str:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Expected {EMBEDDING_DIMENSIONS}-dimensional embeddings.")
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"
