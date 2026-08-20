import hashlib
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import get_settings


class InMemoryRateLimiter:
    """A process-local sliding-window limiter for the single-instance fallback."""

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int, int]:
        current_time = now if now is not None else time.monotonic()
        cutoff = current_time - self.window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - current_time))
                return False, 0, retry_after
            events.append(current_time)
            return True, self.limit - len(events), 0


class RedisRateLimiter:
    """Use a Redis fixed-window counter for limits shared across API instances."""

    def __init__(self, client: Any, *, namespace: str = "asianode:rate-limit") -> None:
        self.client = client
        self.namespace = namespace

    async def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> tuple[bool, int, int]:
        current_time = now if now is not None else time.time()
        window_id = int(current_time // window_seconds)
        fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        bucket_key = f"{self.namespace}:{window_seconds}:{window_id}:{fingerprint}"
        count = int(await self.client.incr(bucket_key))
        if count == 1:
            await self.client.expire(bucket_key, window_seconds + 1)

        remaining = max(0, limit - count)
        retry_after = max(1, window_seconds - int(current_time % window_seconds))
        return count <= limit, remaining, retry_after if count > limit else 0


def _client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    authorization = request.headers.get("authorization", "")
    token_fingerprint = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:16]
    return f"{host}:{token_fingerprint}:{request.method}:{request.url.path}"


def _path_limit(path: str, default_limit: int) -> int:
    if path == "/api/v1/auth/bootstrap":
        return min(default_limit, 10)
    if path == "/api/v1/chat":
        return min(default_limit, 20)
    if "/files" in path:
        return min(default_limit, 30)
    return default_limit


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable,
        *,
        limit: int,
        window_seconds: int,
        redis_client: Any | None = None,
    ) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self._limiters: dict[int, InMemoryRateLimiter] = {}
        self._lock = threading.Lock()
        self._redis_limiter = RedisRateLimiter(redis_client) if redis_client else None

    def _limiter_for(self, limit: int) -> InMemoryRateLimiter:
        with self._lock:
            limiter = self._limiters.get(limit)
            if limiter is None:
                limiter = InMemoryRateLimiter(
                    limit=limit,
                    window_seconds=self.window_seconds,
                )
                self._limiters[limit] = limiter
            return limiter

    def _redis_limiter_for(self, settings: Any) -> RedisRateLimiter | None:
        if not settings.rate_limit_redis_enabled or not settings.redis_url:
            return None
        if self._redis_limiter is None:
            try:
                self._redis_limiter = RedisRateLimiter(
                    Redis.from_url(settings.redis_url, decode_responses=True)
                )
            except (OSError, ValueError, RedisError):
                return None
        return self._redis_limiter

    async def _check_limit(
        self,
        key: str,
        *,
        limit: int,
        settings: Any,
    ) -> tuple[bool, int, int]:
        redis_limiter = self._redis_limiter_for(settings)
        if redis_limiter is not None:
            try:
                return await redis_limiter.check(
                    key,
                    limit=limit,
                    window_seconds=self.window_seconds,
                )
            except (OSError, RedisError):
                pass
        return self._limiter_for(limit).check(key)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not settings.rate_limit_enabled or not request.url.path.startswith("/api/v1/"):
            return await call_next(request)
        if request.url.path in {"/api/v1/healthz", "/api/v1/docs", "/api/v1/openapi.json"}:
            return await call_next(request)

        limit = _path_limit(request.url.path, self.limit)
        allowed, remaining, retry_after = await self._check_limit(
            _client_key(request),
            limit=limit,
            settings=settings,
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limit:exceeded",
                    "message": "Too many requests. Please retry later.",
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
