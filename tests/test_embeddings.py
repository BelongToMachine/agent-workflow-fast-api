import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.embeddings import (
    EmbeddingProviderError,
    embed_texts,
)


class FakeEmbeddingResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeEmbeddingClient:
    def __init__(self, response: FakeEmbeddingResponse | Exception) -> None:
        self.response = response
        self.timeout = None
        self.requests: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, _url: str, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _embedding(value: float) -> list[float]:
    return [value] * 1536


def test_embedding_provider_uses_configured_timeout_and_restores_response_order(
    monkeypatch,
) -> None:
    client = FakeEmbeddingClient(
        FakeEmbeddingResponse(
            {
                "data": [
                    {"index": 1, "embedding": _embedding(0.2)},
                    {"index": 0, "embedding": _embedding(0.1)},
                ]
            }
        )
    )
    settings = Settings(
        embedding_api_key="test-key",
        embedding_provider_timeout_seconds=7.5,
    )
    monkeypatch.setattr(
        "app.services.embeddings.httpx.AsyncClient",
        lambda **kwargs: (setattr(client, "timeout", kwargs["timeout"]) or client),
    )

    vectors = asyncio.run(embed_texts(["first", "second"], settings))

    assert client.timeout == 7.5
    assert client.requests[0]["json"] == {
        "input": ["first", "second"],
        "model": settings.embedding_model,
    }
    assert vectors[0][0] == 0.1
    assert vectors[1][0] == 0.2


def test_embedding_provider_rejects_invalid_vector_shape(monkeypatch) -> None:
    client = FakeEmbeddingClient(
        FakeEmbeddingResponse({"data": [{"index": 0, "embedding": [0.1]}]})
    )
    monkeypatch.setattr("app.services.embeddings.httpx.AsyncClient", lambda **_kwargs: client)

    with pytest.raises(EmbeddingProviderError, match="1536-dimensional"):
        asyncio.run(
            embed_texts(
                ["query"],
                Settings(embedding_api_key="test-key"),
            )
        )


def test_embedding_provider_converts_transport_failures_to_safe_error(monkeypatch) -> None:
    client = FakeEmbeddingClient(httpx.ReadTimeout("provider timed out"))
    monkeypatch.setattr("app.services.embeddings.httpx.AsyncClient", lambda **_kwargs: client)

    with pytest.raises(EmbeddingProviderError, match="request failed"):
        asyncio.run(
            embed_texts(
                ["query"],
                Settings(embedding_api_key="test-key"),
            )
        )


def test_embedding_provider_timeout_has_safe_bounds() -> None:
    settings = Settings(EMBEDDING_PROVIDER_TIMEOUT_SECONDS=12.5)
    assert settings.embedding_provider_timeout_seconds == 12.5

    with pytest.raises(ValidationError):
        Settings(EMBEDDING_PROVIDER_TIMEOUT_SECONDS=0.5)


@pytest.mark.parametrize("indexes", [[0, 0], [0, 2], [0, "1"], [False, 1], [None, 1]])
def test_embedding_provider_rejects_invalid_indexes(monkeypatch, indexes) -> None:
    client = FakeEmbeddingClient(FakeEmbeddingResponse({"data": [
        {"index": index, "embedding": _embedding(0.1)} for index in indexes
    ]}))
    monkeypatch.setattr("app.services.embeddings.httpx.AsyncClient", lambda **_kwargs: client)
    with pytest.raises(EmbeddingProviderError):
        asyncio.run(embed_texts(["first", "second"], Settings(embedding_api_key="test-key")))


@pytest.mark.parametrize("value", [None, {}, "bad", True, float("inf"), float("nan")])
def test_embedding_provider_rejects_invalid_components(monkeypatch, value) -> None:
    vector = _embedding(0.1)
    vector[0] = value
    client = FakeEmbeddingClient(FakeEmbeddingResponse({"data": [
        {"index": 0, "embedding": vector}
    ]}))
    monkeypatch.setattr("app.services.embeddings.httpx.AsyncClient", lambda **_kwargs: client)
    with pytest.raises(EmbeddingProviderError):
        asyncio.run(embed_texts(["query"], Settings(embedding_api_key="test-key")))


def test_embedding_requests_are_batched_with_one_client(monkeypatch) -> None:
    requests = []

    class BatchClient(FakeEmbeddingClient):
        async def post(self, _url, **kwargs):
            inputs = kwargs["json"]["input"]
            requests.append(inputs)
            return FakeEmbeddingResponse({"data": [
                {"index": i, "embedding": _embedding(float(value))}
                for i, value in reversed(list(enumerate(inputs)))
            ]})

    client = BatchClient(None)
    created = []

    def make_client(**_kwargs):
        created.append(client)
        return client

    monkeypatch.setattr("app.services.embeddings.httpx.AsyncClient", make_client)
    texts = [str(i) for i in range(300)]
    vectors = asyncio.run(embed_texts(texts, Settings(embedding_api_key="test-key")))
    assert [vector[0] for vector in vectors] == [float(i) for i in range(300)]
    assert len(requests) > 1
    assert [text for batch in requests for text in batch] == texts
    assert len(created) == 1
