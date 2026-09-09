"""Opaque one-time token helpers for invitations and password recovery."""

import hashlib
import secrets
from dataclasses import dataclass

ONE_TIME_TOKEN_BYTES = 32


@dataclass(frozen=True)
class NewOneTimeToken:
    token: str
    token_hash: str


def new_one_time_token() -> NewOneTimeToken:
    """Generate a URL-safe token and its database-safe hash."""
    token = secrets.token_urlsafe(ONE_TIME_TOKEN_BYTES)
    return NewOneTimeToken(
        token=token,
        token_hash=hash_one_time_token(token),
    )


def hash_one_time_token(token: str) -> str:
    """Hash a token before it is persisted or used in a query."""
    if not isinstance(token, str) or not token:
        raise ValueError("One-time token must be a non-empty string.")
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("One-time token must contain ASCII characters only.") from error
    return hashlib.sha256(token_bytes).hexdigest()
