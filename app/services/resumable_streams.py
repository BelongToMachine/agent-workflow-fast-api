import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

STREAM_KEY_PREFIX = "asianode:chat-stream"
POLL_INTERVAL_SECONDS = 0.2


class ResumableStreamStore:
    """Persist SSE chunks in Redis so a chat can be resumed without sticky sessions."""

    def __init__(
        self,
        redis_url: str | None,
        ttl_seconds: int,
        *,
        client: Any | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._redis = client or (
            Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        )

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    @staticmethod
    def _active_key(chat_id: str) -> str:
        return f"{STREAM_KEY_PREFIX}:active:{chat_id}"

    @staticmethod
    def _chunks_key(stream_id: str) -> str:
        return f"{STREAM_KEY_PREFIX}:chunks:{stream_id}"

    @staticmethod
    def _done_key(stream_id: str) -> str:
        return f"{STREAM_KEY_PREFIX}:done:{stream_id}"

    async def _start(self, chat_id: str, stream_id: str) -> bool:
        if not self.enabled:
            return False
        try:
            await self._redis.delete(
                self._chunks_key(stream_id),
                self._done_key(stream_id),
            )
            await self._redis.set(
                self._active_key(chat_id),
                stream_id,
                ex=self.ttl_seconds,
            )
            return True
        except RedisError:
            return False

    async def _append(self, stream_id: str, chunk: str) -> None:
        if not self.enabled:
            return
        await self._redis.rpush(self._chunks_key(stream_id), chunk)
        await self._redis.expire(self._chunks_key(stream_id), self.ttl_seconds)

    async def _finish(self, chat_id: str, stream_id: str) -> None:
        if not self.enabled:
            return
        try:
            await self._redis.set(
                self._done_key(stream_id),
                "1",
                ex=self.ttl_seconds,
            )
            if await self._redis.get(self._active_key(chat_id)) == stream_id:
                await self._redis.expire(
                    self._active_key(chat_id),
                    self.ttl_seconds,
                )
        except RedisError:
            return

    async def capture(
        self,
        chat_id: str,
        source: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Yield the source immediately while best-effort persisting every SSE chunk."""
        if not self.enabled:
            async for chunk in source:
                yield chunk
            return

        stream_id = str(uuid4())
        started = await self._start(chat_id, stream_id)
        persisted = started
        try:
            async for chunk in source:
                if persisted:
                    try:
                        await self._append(stream_id, chunk)
                    except RedisError:
                        persisted = False
                yield chunk
        finally:
            if started:
                await self._finish(chat_id, stream_id)

    async def active_stream_id(self, chat_id: str) -> str | None:
        if not self.enabled:
            return None
        try:
            value = await self._redis.get(self._active_key(chat_id))
        except RedisError:
            return None
        return str(value) if value else None

    async def resume(self, chat_id: str, stream_id: str) -> AsyncIterator[str]:
        """Read buffered chunks and follow new chunks until the producer finishes."""
        if not self.enabled:
            return

        chunks_key = self._chunks_key(stream_id)
        done_key = self._done_key(stream_id)
        active_key = self._active_key(chat_id)
        index = 0

        while True:
            try:
                if await self._redis.get(active_key) != stream_id:
                    return

                chunks = await self._redis.lrange(chunks_key, index, -1)
                for chunk in chunks:
                    index += 1
                    yield str(chunk)

                if await self._redis.exists(done_key):
                    return
            except RedisError:
                return

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


@lru_cache(maxsize=8)
def get_resumable_stream_store(
    redis_url: str | None,
    ttl_seconds: int,
) -> ResumableStreamStore:
    return ResumableStreamStore(redis_url, ttl_seconds)
