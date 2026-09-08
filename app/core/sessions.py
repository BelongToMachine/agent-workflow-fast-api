"""Opaque browser session token helpers."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

SESSION_TOKEN_BYTES = 32
SESSION_COOKIE_NAME = "__Host-asianode_session"


@dataclass(frozen=True)
class NewSessionToken:
    session_id: UUID
    token: str
    token_hash: str


def generate_session_token() -> str:
    """Generate an opaque token with at least 256 bits of randomness."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Hash a browser token before it is persisted or used in a query."""
    if not isinstance(token, str) or not token:
        raise ValueError("Session token must be a non-empty string.")
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("Session token must contain ASCII characters only.") from error
    return hashlib.sha256(token_bytes).hexdigest()


def new_session_token() -> NewSessionToken:
    token = generate_session_token()
    return NewSessionToken(
        session_id=uuid4(),
        token=token,
        token_hash=hash_session_token(token),
    )


def hash_client_metadata(value: str | None, *, pepper: str) -> str | None:
    """Return a keyed hash for low-entropy client metadata such as an IP."""
    if value is None:
        return None
    if not pepper:
        raise ValueError("A non-empty metadata pepper is required.")
    return hmac.new(
        pepper.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def session_is_expired(
    *,
    now: datetime,
    idle_expires_at: datetime,
    absolute_expires_at: datetime,
) -> bool:
    return now >= idle_expires_at or now >= absolute_expires_at
