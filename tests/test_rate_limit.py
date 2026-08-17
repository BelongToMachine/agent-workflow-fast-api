import asyncio

from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimitMiddleware,
    RedisRateLimiter,
    _path_limit,
)


def test_in_memory_rate_limiter_returns_retry_after_when_exhausted() -> None:
    limiter = InMemoryRateLimiter(limit=2, window_seconds=60)

    assert limiter.check("user", now=100)[0:2] == (True, 1)
    assert limiter.check("user", now=101)[0:2] == (True, 0)
    allowed, remaining, retry_after = limiter.check("user", now=102)

    assert (allowed, remaining) == (False, 0)
    assert retry_after >= 1


def test_rate_limit_is_stricter_for_expensive_routes() -> None:
    assert _path_limit("/api/v1/chat", 120) == 20
    assert _path_limit("/api/v1/knowledge-bases/a/files", 120) == 30
    assert _path_limit("/api/v1/products", 120) == 120


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


def test_redis_rate_limiter_shares_a_fixed_window_counter() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis)

    first = asyncio.run(
        limiter.check("user", limit=2, window_seconds=60, now=120.0)
    )
    second = asyncio.run(
        limiter.check("user", limit=2, window_seconds=60, now=121.0)
    )
    blocked = asyncio.run(
        limiter.check("user", limit=2, window_seconds=60, now=122.0)
    )

    assert first == (True, 1, 0)
    assert second == (True, 0, 0)
    assert blocked == (False, 0, 58)
    assert list(redis.expirations.values()) == [61]


class BrokenRedis:
    async def incr(self, _key: str) -> int:
        raise RedisError("Redis is unavailable")


def test_rate_limit_falls_back_to_process_local_storage_when_redis_fails() -> None:
    middleware = RateLimitMiddleware(
        lambda *_args, **_kwargs: None,
        limit=2,
        window_seconds=60,
        redis_client=BrokenRedis(),
    )
    settings = Settings(
        redis_url="redis://127.0.0.1:6379/0",
        rate_limit_redis_enabled=True,
    )

    first = asyncio.run(
        middleware._check_limit("user", limit=2, settings=settings)
    )
    second = asyncio.run(
        middleware._check_limit("user", limit=2, settings=settings)
    )
    blocked = asyncio.run(
        middleware._check_limit("user", limit=2, settings=settings)
    )

    assert first[0:2] == (True, 1)
    assert second[0:2] == (True, 0)
    assert blocked[0:2] == (False, 0)
