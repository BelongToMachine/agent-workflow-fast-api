"""CSRF token, strict Origin validation, and browser request protection."""

import hmac
import secrets
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.sessions import SESSION_COOKIE_NAME

CSRF_TOKEN_BYTES = 32
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_NAME = "__Host-asianode_csrf"
CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_ROUTE_VALIDATED_PREFIXES = ("/api/v1/auth/",)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def validate_csrf_token(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    try:
        expected_bytes = expected.encode("ascii")
        provided_bytes = provided.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(expected_bytes, provided_bytes)


def is_allowed_origin(origin: str | None, allowed_origins: list[str] | tuple[str, ...]) -> bool:
    """Require an exact configured Origin; ``null`` and missing values fail."""
    if not origin or origin == "null":
        return False
    return origin in {configured.strip() for configured in allowed_origins if configured.strip()}


def _csrf_error(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"code": code, "detail": {"code": code, "message": message}, "message": message},
    )


class CSRFMiddleware(BaseHTTPMiddleware):
    """Protect state-changing API requests authenticated by a browser cookie.

    Login and other unauthenticated auth mutations retain their route-level
    CSRF dependency. This middleware covers the remaining API mutations when a
    local session cookie is present, including chat, document, and admin APIs.
    Bearer-only requests do not need CSRF protection because browsers do not
    attach the Authorization header automatically.
    """

    def __init__(
        self,
        app: Callable[..., Any],
        *,
        allowed_origins: list[str] | tuple[str, ...],
    ) -> None:
        super().__init__(app)
        self.allowed_origins = tuple(allowed_origins)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        should_check = (
            request.method.upper() in CSRF_PROTECTED_METHODS
            and request.url.path.startswith("/api/v1/")
            and not any(
                request.url.path.startswith(prefix)
                for prefix in CSRF_ROUTE_VALIDATED_PREFIXES
            )
            and SESSION_COOKIE_NAME in request.cookies
        )
        if not should_check:
            return await call_next(request)

        if not is_allowed_origin(request.headers.get("origin"), self.allowed_origins):
            return _csrf_error("csrf:origin_invalid", "Request origin is not allowed.")

        if not validate_csrf_token(
            request.cookies.get(CSRF_COOKIE_NAME),
            request.headers.get(CSRF_HEADER_NAME),
        ):
            return _csrf_error(
                "csrf:token_invalid",
                "CSRF token is missing or invalid.",
            )

        return await call_next(request)
