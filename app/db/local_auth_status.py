"""Read-only status checks for the local authentication schema."""

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import text

from app.db.session import get_db_connection

LOCAL_AUTH_STATUS_QUERY = text(
    """
    SELECT
        to_regclass('public."PasswordCredential"') IS NOT NULL AS password_table,
        (
            SELECT COUNT(*) = 6
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'PasswordCredential'
              AND column_name IN (
                  'createdAt', 'passwordChangedAt', 'passwordHash',
                  'passwordVersion', 'updatedAt', 'userId'
              )
        ) AS password_required_columns,
        to_regclass('public."AuthSession"') IS NOT NULL AS session_table,
        (
            SELECT COUNT(*) = 10
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'AuthSession'
              AND column_name IN (
                  'absoluteExpiresAt', 'createdAt', 'idleExpiresAt', 'id',
                  'ipHash', 'lastSeenAt', 'revokedAt', 'tokenHash',
                  'userAgentHash', 'userId'
              )
        ) AS session_required_columns,
        to_regclass('public."AuthOneTimeToken"') IS NOT NULL AS one_time_table,
        (
            SELECT COUNT(*) = 12
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'AuthOneTimeToken'
              AND column_name IN (
                  'createdAt', 'createdBy', 'expiresAt', 'id', 'normalizedEmail',
                  'purpose', 'revokedAt', 'tokenHash', 'usedAt', 'userId',
                  'workspaceId', 'workspaceRole'
              )
        ) AS one_time_required_columns,
        to_regclass('public."AuthAuditLog"') IS NOT NULL AS audit_table,
        (
            SELECT COUNT(*) = 8
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'AuthAuditLog'
              AND column_name IN (
                  'createdAt', 'eventType', 'id', 'ipHash', 'metadata',
                  'sessionId', 'userAgentHash', 'userId'
              )
        ) AS audit_required_columns,
        to_regclass('public."AuthSession_user_active_idx"') IS NOT NULL
            AS session_index,
        to_regclass('public."AuthOneTimeToken_user_purpose_idx"') IS NOT NULL
            AS one_time_index,
        to_regclass('public."AuthAuditLog_user_created_idx"') IS NOT NULL
            AS audit_index
    """
)


@dataclass(frozen=True)
class LocalAuthMigrationStatus:
    name: str
    applied: bool
    details: str


def build_local_auth_status(row: dict[str, object]) -> LocalAuthMigrationStatus:
    required_flags = (
        "password_table",
        "password_required_columns",
        "session_table",
        "session_required_columns",
        "one_time_table",
        "one_time_required_columns",
        "audit_table",
        "audit_required_columns",
        "session_index",
        "one_time_index",
        "audit_index",
    )
    applied = all(bool(row.get(flag, False)) for flag in required_flags)
    return LocalAuthMigrationStatus(
        name="0010_local_auth",
        applied=applied,
        details=(
            "PasswordCredential, AuthSession, AuthOneTimeToken, AuthAuditLog "
            "tables, required columns, and indexes"
        ),
    )


async def _run() -> int:
    async with get_db_connection() as connection:
        result = await connection.execute(LOCAL_AUTH_STATUS_QUERY)
        status = build_local_auth_status(dict(result.mappings().one()))

    state = "applied" if status.applied else "pending"
    print(f"{status.name}: {state} ({status.details})")
    return 0 if status.applied else 2


def main() -> None:
    argparse.ArgumentParser(
        description="Inspect the local authentication schema status."
    ).parse_args()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
