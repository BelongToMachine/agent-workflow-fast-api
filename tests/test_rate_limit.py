import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from starlette.requests import Request

from app.core.config import Settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimitMiddleware,
    RedisRateLimiter,
    _client_key,
    _path_limit,
)
from app.main import app, create_app

client = TestClient(app)


def test_in_memory_rate_limiter_returns_retry_after_when_exhausted() -> None:
    limiter = InMemoryRateLimiter(limit=2, window_seconds=60)

    assert limiter.check("user", now=100)[0:2] == (True, 1)
    assert limiter.check("user", now=101)[0:2] == (True, 0)
    allowed, remaining, retry_after = limiter.check("user", now=102)

    assert (allowed, remaining) == (False, 0)
    assert retry_after >= 1


def test_idle_rate_limit_keys_are_reclaimed() -> None:
    limiter = InMemoryRateLimiter(limit=2, window_seconds=60)
    for index in range(1000):
        limiter.check(str(index), now=100)
    limiter.check("active", now=161)
    assert len(limiter._events) == 1


def test_fractional_retry_after_rounds_up() -> None:
    limiter = InMemoryRateLimiter(limit=1, window_seconds=60)
    limiter.check("user", now=100)
    assert limiter.check("user", now=100.1)[2] == 60


def test_rate_limit_is_stricter_for_expensive_routes() -> None:
    assert _path_limit("/api/v1/auth/password-reset/request", 120) == 10
    assert _path_limit("/api/v1/auth/change-password", 120, auth_limit=7) == 7
    assert _path_limit("/api/v1/admin/auth/invitations", 120) == 10
    assert _path_limit("/api/v1/chat", 120) == 20
    assert _path_limit("/api/v1/knowledge-bases/a/files", 120) == 30
    assert _path_limit("/api/v1/products", 120) == 120


def test_local_session_cookie_is_part_of_rate_limit_key() -> None:
    first = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/change-password",
        "headers": [(b"cookie", b"__Host-asianode_session=session-a")],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
    })
    second = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/change-password",
        "headers": [(b"cookie", b"__Host-asianode_session=session-b")],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
    })
    assert _client_key(first) != _client_key(second)


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


def test_rate_limit_middleware_returns_http_429_with_contract_headers(monkeypatch) -> None:
    settings = Settings(
        environment="development",
        rate_limit_enabled=True,
        rate_limit_redis_enabled=False,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
    )
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    test_client = TestClient(create_app())
    authorization = f"Bearer rate-limit-test-{uuid4()}"

    first = test_client.get(
        "/api/v1/models",
        headers={"authorization": authorization},
    )
    second = test_client.get(
        "/api/v1/models",
        headers={"authorization": authorization},
    )

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "1"
    assert first.headers["x-ratelimit-remaining"] == "0"
    assert second.status_code == 429
    assert second.json() == {
        "code": "rate_limit:exceeded",
        "message": "Too many requests. Please retry later.",
    }
    assert second.headers["x-ratelimit-limit"] == "1"
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert int(second.headers["retry-after"]) >= 1
