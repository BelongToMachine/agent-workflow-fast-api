"""CSRF token and strict Origin validation helpers."""

import hmac
import secrets

CSRF_TOKEN_BYTES = 32
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_NAME = "__Host-asianode_csrf"


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
