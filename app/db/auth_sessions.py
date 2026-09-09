"""Database repository for opaque local-authentication sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.sessions import hash_session_token, new_session_token


@dataclass(frozen=True)
class AuthSessionRecord:
    session_id: UUID
    user_id: UUID
    token_hash: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None
    user_status: str


CREATE_SESSION_QUERY = text(
    """
    INSERT INTO "AuthSession" (
        "id", "userId", "tokenHash", "createdAt", "lastSeenAt",
        "idleExpiresAt", "absoluteExpiresAt", "ipHash", "userAgentHash"
    )
    SELECT
        :session_id, :user_id, :token_hash, :created_at, :last_seen_at,
        :idle_expires_at, :absolute_expires_at, :ip_hash, :user_agent_hash
    FROM "User"
    WHERE "id" = :user_id AND "status" = 'active'
    RETURNING
        "id" AS session_id,
        "userId" AS user_id,
        "tokenHash" AS token_hash,
        "createdAt" AS created_at,
        "lastSeenAt" AS last_seen_at,
        "idleExpiresAt" AS idle_expires_at,
        "absoluteExpiresAt" AS absolute_expires_at,
        "revokedAt" AS revoked_at
    """
)

GET_SESSION_QUERY = text(
    """
    SELECT
        session."id" AS session_id,
        session."userId" AS user_id,
        session."tokenHash" AS token_hash,
        session."createdAt" AS created_at,
        session."lastSeenAt" AS last_seen_at,
        session."idleExpiresAt" AS idle_expires_at,
        session."absoluteExpiresAt" AS absolute_expires_at,
        session."revokedAt" AS revoked_at,
        user_record."status" AS user_status
    FROM "AuthSession" AS session
    INNER JOIN "User" AS user_record
        ON user_record."id" = session."userId"
    WHERE session."tokenHash" = :token_hash
      AND session."revokedAt" IS NULL
      AND session."idleExpiresAt" > CURRENT_TIMESTAMP
      AND session."absoluteExpiresAt" > CURRENT_TIMESTAMP
    """
)

TOUCH_SESSION_QUERY = text(
    """
    UPDATE "AuthSession"
    SET "lastSeenAt" = :last_seen_at,
        "idleExpiresAt" = LEAST(:idle_expires_at, "absoluteExpiresAt")
    WHERE "id" = :session_id
      AND "revokedAt" IS NULL
      AND "lastSeenAt" < :touch_after
      AND "absoluteExpiresAt" > :last_seen_at
    """
)

REVOKE_SESSION_QUERY = text(
    """
    UPDATE "AuthSession"
    SET "revokedAt" = :revoked_at
    WHERE "id" = :session_id
      AND "revokedAt" IS NULL
    """
)

REVOKE_USER_SESSIONS_QUERY = text(
    """
    UPDATE "AuthSession"
    SET "revokedAt" = :revoked_at
    WHERE "userId" = :user_id
      AND "revokedAt" IS NULL
      AND (:except_session_id IS NULL OR "id" <> :except_session_id)
    """
)


def _record_from_row(row: dict[str, object]) -> AuthSessionRecord:
    return AuthSessionRecord(
        session_id=UUID(str(row["session_id"])),
        user_id=UUID(str(row["user_id"])),
        token_hash=str(row["token_hash"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
        last_seen_at=row["last_seen_at"],  # type: ignore[arg-type]
        idle_expires_at=row["idle_expires_at"],  # type: ignore[arg-type]
        absolute_expires_at=row["absolute_expires_at"],  # type: ignore[arg-type]
        revoked_at=row["revoked_at"],  # type: ignore[arg-type]
        user_status=str(row["user_status"]),
    )


class AuthSessionRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def create(
        self,
        *,
        user_id: UUID,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
        now: datetime | None = None,
    ) -> NewSessionTokenRecord:
        current = now or datetime.now(UTC).replace(tzinfo=None)
        token = new_session_token()
        idle_expires_at = current + idle_timeout
        absolute_expires_at = current + absolute_timeout
        result = await self.connection.execute(
            CREATE_SESSION_QUERY,
            {
                "session_id": token.session_id,
                "user_id": user_id,
                "token_hash": token.token_hash,
                "created_at": current,
                "last_seen_at": current,
                "idle_expires_at": idle_expires_at,
                "absolute_expires_at": absolute_expires_at,
                "ip_hash": ip_hash,
                "user_agent_hash": user_agent_hash,
            },
        )
        row = result.mappings().one()
        record = _record_from_row({**row, "user_status": "active"})
        return NewSessionTokenRecord(token=token.token, record=record)

    async def get_active(self, token: str) -> AuthSessionRecord | None:
        result = await self.connection.execute(
            GET_SESSION_QUERY,
            {"token_hash": hash_session_token(token)},
        )
        row = result.mappings().first()
        return _record_from_row(dict(row)) if row is not None else None

    async def touch(
        self,
        record: AuthSessionRecord,
        *,
        idle_timeout: timedelta,
        touch_after: datetime,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(UTC).replace(tzinfo=None)
        await self.connection.execute(
            TOUCH_SESSION_QUERY,
            {
                "session_id": record.session_id,
                "last_seen_at": current,
                "idle_expires_at": current + idle_timeout,
                "touch_after": touch_after,
            },
        )

    async def revoke(self, session_id: UUID, *, now: datetime | None = None) -> None:
        await self.connection.execute(
            REVOKE_SESSION_QUERY,
            {
                "session_id": session_id,
                "revoked_at": now or datetime.now(UTC).replace(tzinfo=None),
            },
        )

    async def revoke_user_sessions(
        self,
        user_id: UUID,
        *,
        except_session_id: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        await self.connection.execute(
            REVOKE_USER_SESSIONS_QUERY,
            {
                "user_id": user_id,
                "except_session_id": except_session_id,
                "revoked_at": now or datetime.now(UTC).replace(tzinfo=None),
            },
        )


@dataclass(frozen=True)
class NewSessionTokenRecord:
    token: str
    record: AuthSessionRecord
