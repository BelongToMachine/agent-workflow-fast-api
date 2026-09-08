from datetime import datetime, timedelta

import pytest

from app.core.sessions import (
    SESSION_TOKEN_BYTES,
    hash_client_metadata,
    hash_session_token,
    new_session_token,
    session_is_expired,
)


def test_new_session_token_is_opaque_and_256_bits() -> None:
    session = new_session_token()

    assert len(session.token_hash) == 64
    assert len(session.token) >= SESSION_TOKEN_BYTES
    assert session.token_hash == hash_session_token(session.token)


def test_session_token_hash_rejects_unicode_values() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        hash_session_token("中文-token")


def test_client_metadata_uses_a_keyed_hash() -> None:
    first = hash_client_metadata("203.0.113.10", pepper="secret-a")
    second = hash_client_metadata("203.0.113.10", pepper="secret-b")

    assert first is not None
    assert first != second
    assert hash_client_metadata(None, pepper="secret-a") is None


def test_session_expiry_checks_idle_and_absolute_deadlines() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)

    assert session_is_expired(
        now=now,
        idle_expires_at=now + timedelta(minutes=1),
        absolute_expires_at=now + timedelta(hours=1),
    ) is False
    assert session_is_expired(
        now=now + timedelta(minutes=1),
        idle_expires_at=now + timedelta(minutes=1),
        absolute_expires_at=now + timedelta(hours=1),
    ) is True
