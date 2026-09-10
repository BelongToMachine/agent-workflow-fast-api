import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.auth_sessions import AuthSessionRecord, AuthSessionRepository


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    async def execute(self, query, params):
        self.calls.append((query, params))


def _record(last_seen_at: datetime, absolute_expires_at: datetime) -> AuthSessionRecord:
    return AuthSessionRecord(
        session_id=uuid4(),
        user_id=uuid4(),
        token_hash="a" * 64,
        created_at=last_seen_at,
        last_seen_at=last_seen_at,
        idle_expires_at=last_seen_at + timedelta(hours=12),
        absolute_expires_at=absolute_expires_at,
        revoked_at=None,
        user_status="active",
    )


def test_touch_if_due_skips_requests_inside_the_touch_window() -> None:
    now = datetime(2026, 9, 10, 12, tzinfo=UTC).replace(tzinfo=None)
    connection = _Connection()
    record = _record(
        now - timedelta(minutes=4),
        now + timedelta(days=2),
    )

    touched = asyncio.run(
        AuthSessionRepository(connection).touch_if_due(
            record,
            idle_timeout=timedelta(hours=12),
            touch_interval=timedelta(minutes=5),
            now=now,
        )
    )

    assert touched is False
    assert connection.calls == []


def test_touch_if_due_advances_idle_expiry_without_crossing_absolute_expiry() -> None:
    now = datetime(2026, 9, 10, 12, tzinfo=UTC).replace(tzinfo=None)
    connection = _Connection()
    record = _record(
        now - timedelta(minutes=6),
        now + timedelta(hours=1),
    )

    touched = asyncio.run(
        AuthSessionRepository(connection).touch_if_due(
            record,
            idle_timeout=timedelta(hours=12),
            touch_interval=timedelta(minutes=5),
            now=now,
        )
    )

    assert touched is True
    assert len(connection.calls) == 1
    query, params = connection.calls[0]
    assert '"idleExpiresAt" = LEAST(:idle_expires_at, "absoluteExpiresAt")' in str(query)
    assert params["last_seen_at"] == now
    assert params["idle_expires_at"] == now + timedelta(hours=12)
