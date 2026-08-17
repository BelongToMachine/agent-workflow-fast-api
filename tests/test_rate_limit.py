from app.core.rate_limit import InMemoryRateLimiter, _path_limit


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
