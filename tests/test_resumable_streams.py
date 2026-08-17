import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.main import app
from app.services.resumable_streams import ResumableStreamStore

client = TestClient(app)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.lists.pop(key, None)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start : end + 1]

    async def exists(self, key: str) -> int:
        return int(key in self.values)


async def _source() -> AsyncIterator[str]:
    yield "data: first\n\n"
    yield "data: second\n\n"


def test_capture_falls_back_to_live_stream_without_redis() -> None:
    store = ResumableStreamStore(None, 60)

    chunks = asyncio.run(_collect(store.capture("chat-id", _source())))

    assert chunks == ["data: first\n\n", "data: second\n\n"]
    assert store.enabled is False


def test_capture_persists_and_resume_replays_completed_stream() -> None:
    redis = FakeRedis()
    store = ResumableStreamStore("redis://unused", 60, client=redis)

    chunks = asyncio.run(_collect(store.capture("chat-id", _source())))
    stream_id = asyncio.run(store.active_stream_id("chat-id"))
    resumed = asyncio.run(_collect(store.resume("chat-id", stream_id or "")))

    assert chunks == resumed
    assert stream_id is not None
    assert redis.values[store._done_key(stream_id)] == "1"


def test_resume_endpoint_returns_no_content_for_development_identity() -> None:
    response = client.get(
        "/api/v1/chat/00000000-0000-0000-0000-000000000010/stream",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 204


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [chunk async for chunk in stream]
