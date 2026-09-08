import re
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response

_ERROR_CODE_PATTERN = re.compile(r"^[a-z_]+:[a-z_]+$")

_DETAIL_CODES = {
    "Bearer access token is required.": "auth:token_missing",
    "Bearer access token is invalid or expired.": "auth:token_invalid",
    "Email or password is incorrect.": "auth:credentials_invalid",
    "Session cookie is required.": "auth:session_missing",
    "Session cookie is invalid or expired.": "auth:session_invalid",
    "Authentication storage is unavailable.": "auth:storage_unavailable",
    "The authenticated user has an invalid workspace context.": "workspace:context_mismatch",
    "The requested workspace does not match the authenticated context.": (
        "workspace:context_mismatch"
    ),
    "The authenticated user is not linked to a local workspace.": "auth_identity:not_initialized",
    "The user has no active membership in this workspace.": "workspace:membership_required",
    "The user does not have permission to access this workspace data.": (
        "workspace:permission_denied"
    ),
    "The development user does not have this permission.": "workspace:permission_denied",
}


def _message_from_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            return message
    return "The request could not be authorized."


def _code_from_detail(status_code: int, detail: Any) -> str:
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and _ERROR_CODE_PATTERN.fullmatch(code):
            return code

    if isinstance(detail, str):
        if _ERROR_CODE_PATTERN.fullmatch(detail):
            return detail
        if detail in _DETAIL_CODES:
            return _DETAIL_CODES[detail]

    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "auth:unauthorized"
    return "authorization:forbidden"


async def structured_http_exception_handler(
    request: Request,
    error: HTTPException,
) -> Response:
    """Return a stable JSON contract for authentication and authorization errors.

    Existing ``detail`` text is retained for API compatibility while clients can
    switch on the stable ``code`` field. Other status codes keep FastAPI's
    standard response shape.
    """
    if error.status_code not in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }:
        return await http_exception_handler(request, error)

    message = _message_from_detail(error.detail)
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": _code_from_detail(error.status_code, error.detail),
            "detail": error.detail,
            "message": message,
        },
        headers=error.headers,
    )
