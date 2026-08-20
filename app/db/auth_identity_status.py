import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import text

from app.db.session import get_db_connection

AUTH_IDENTITY_STATUS_QUERY = text(
    """
    SELECT
        to_regclass('public."User"') IS NOT NULL AS user_table,
        (
            SELECT COUNT(*) = 3
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'User'
              AND column_name IN ('id', 'email', 'status')
        ) AS user_required_columns,
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'User'
              AND column_name = 'email'
              AND is_nullable = 'YES'
              AND data_type IN ('character varying', 'text')
              AND (
                  character_maximum_length IS NULL
                  OR character_maximum_length >= 320
              )
        ) AS user_email_compatible,
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'User'
              AND column_name = 'status'
              AND is_nullable = 'NO'
              AND column_default LIKE '%active%'
        ) AS user_status_column,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."User"')
              AND conname = 'User_status_check'
        ) AS user_status_check,
        to_regclass('public."ExternalIdentity"') IS NOT NULL AS identity_table,
        (
            SELECT COUNT(*) = 7
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ExternalIdentity'
              AND column_name IN (
                  'createdAt', 'id', 'lastLoginAt', 'provider', 'subject',
                  'updatedAt', 'userId'
              )
        ) AS identity_required_columns,
        to_regclass('public."ExternalIdentity_user_idx"') IS NOT NULL
            AS identity_user_idx,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."ExternalIdentity"')
              AND conname = 'ExternalIdentity_user_fk'
        ) AS identity_user_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."ExternalIdentity"')
              AND conname = 'ExternalIdentity_provider_subject_key'
        ) AS identity_provider_subject_key
    """
)


@dataclass(frozen=True)
class AuthIdentityMigrationStatus:
    name: str
    applied: bool
    details: str


def build_auth_identity_status(row: dict[str, object]) -> AuthIdentityMigrationStatus:
    def flag(name: str) -> bool:
        return bool(row.get(name, False))

    applied = all(
        flag(key)
        for key in (
            "user_table",
            "user_required_columns",
            "user_email_compatible",
            "user_status_column",
            "user_status_check",
            "identity_table",
            "identity_required_columns",
            "identity_user_idx",
            "identity_user_fk",
            "identity_provider_subject_key",
        )
    )
    return AuthIdentityMigrationStatus(
        name="0005_auth_identity",
        applied=applied,
        details=(
            "nullable User.email, User.status, ExternalIdentity mapping, "
            "unique provider/subject constraint, and User foreign key"
        ),
    )


async def _run() -> int:
    async with get_db_connection() as connection:
        result = await connection.execute(AUTH_IDENTITY_STATUS_QUERY)
        row = dict(result.mappings().one())

    status = build_auth_identity_status(row)
    state = "applied" if status.applied else "pending"
    print(f"{status.name}: {state} ({status.details})")
    return 0 if status.applied else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the auth identity migration status.")
    parser.parse_args()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
