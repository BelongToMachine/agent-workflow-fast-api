"""Read-only checks for the local-authentication migration preflight."""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

from sqlalchemy import text

from app.db.session import get_db_connection

AUTH_MIGRATION_PREFLIGHT_QUERY = text(
    """
    SELECT
        (SELECT COUNT(*) FROM "User") AS user_count,
        (SELECT COUNT(*) FROM "ExternalIdentity") AS external_identity_count,
        (SELECT COUNT(*) FROM "WorkspaceMember") AS workspace_member_count,
        (SELECT COUNT(*) FROM "WorkspaceMemberPermission") AS permission_count,
        (
            SELECT COUNT(*)
            FROM (
                SELECT lower(btrim("email")) AS normalized_email
                FROM "User"
                WHERE "email" IS NOT NULL AND btrim("email") <> ''
                GROUP BY lower(btrim("email"))
                HAVING COUNT(*) > 1
            ) AS duplicate_emails
        ) AS duplicate_email_groups,
        (
            SELECT COUNT(*)
            FROM "User"
            WHERE "email" IS NOT NULL
              AND (
                  btrim("email") = ''
                  OR btrim("email") !~* '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
              )
        ) AS invalid_email_count
    """
)


@dataclass(frozen=True)
class AuthMigrationPreflight:
    user_count: int
    external_identity_count: int
    workspace_member_count: int
    permission_count: int
    duplicate_email_groups: int
    invalid_email_count: int

    @property
    def safe_for_identity_mapping(self) -> bool:
        return self.duplicate_email_groups == 0 and self.invalid_email_count == 0


def build_auth_migration_preflight(row: dict[str, object]) -> AuthMigrationPreflight:
    def count(name: str) -> int:
        value = row.get(name, 0)
        return int(value or 0)

    return AuthMigrationPreflight(
        user_count=count("user_count"),
        external_identity_count=count("external_identity_count"),
        workspace_member_count=count("workspace_member_count"),
        permission_count=count("permission_count"),
        duplicate_email_groups=count("duplicate_email_groups"),
        invalid_email_count=count("invalid_email_count"),
    )


async def _run() -> int:
    async with get_db_connection() as connection:
        result = await connection.execute(AUTH_MIGRATION_PREFLIGHT_QUERY)
        preflight = build_auth_migration_preflight(dict(result.mappings().one()))

    print(json.dumps(asdict(preflight), sort_keys=True))
    return 0 if preflight.safe_for_identity_mapping else 2


def main() -> None:
    argparse.ArgumentParser(
        description="Run read-only checks before local authentication migration."
    ).parse_args()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
