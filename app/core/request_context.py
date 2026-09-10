import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    method: str
    path: str


_request_context: ContextVar[RequestContext | None] = ContextVar(
    "request_context",
    default=None,
)


def request_id_for(request: Request) -> str:
    """Return the validated correlation ID associated with one request."""
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str) and _REQUEST_ID_PATTERN.fullmatch(existing):
        return existing

    received = request.headers.get(REQUEST_ID_HEADER)
    request_id = received if received and _REQUEST_ID_PATTERN.fullmatch(received) else uuid4().hex
    request.state.request_id = request_id
    return request_id


def get_request_context() -> RequestContext | None:
    return _request_context.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to responses and database logs for correlation."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request_id_for(request)
        token = _request_context.set(
            RequestContext(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
            )
        )
        try:
            response = await call_next(request)
        finally:
            _request_context.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
