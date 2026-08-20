import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.db.auth_identity_status import (
    AUTH_IDENTITY_STATUS_QUERY,
    build_auth_identity_status,
)
from app.db.migration_utils import migration_apply_error, split_sql_statements
from app.db.session import get_db_connection

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "0005_auth_identity.sql"
)
PREREQUISITE_QUERY = text(
    """
    SELECT
        to_regclass('public."User"') IS NOT NULL AS user_table,
        (
            SELECT COUNT(*) = 2
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'User'
              AND column_name IN ('id', 'email')
        ) AS user_required_columns
    """
)


async def _run(*, apply: bool, allow_remote: bool = False) -> int:
    if not MIGRATION_PATH.is_file():
        print(f"Migration file not found: {MIGRATION_PATH}")
        return 1

    settings = get_settings()
    if apply:
        if error := migration_apply_error(settings, allow_remote=allow_remote):
            print(error)
            return 1

    async with get_db_connection() as connection:
        async with connection.begin():
            prerequisite_result = await connection.execute(PREREQUISITE_QUERY)
            prerequisites = prerequisite_result.mappings().one()
            if not prerequisites["user_table"] or not prerequisites["user_required_columns"]:
                print(
                    'The existing "User" table with "id" and "email" is required '
                    "before applying 0005_auth_identity."
                )
                return 1

            status_result = await connection.execute(AUTH_IDENTITY_STATUS_QUERY)
            status = build_auth_identity_status(dict(status_result.mappings().one()))
            if status.applied:
                print("Auth identity migration is already applied; nothing to do.")
                return 0

            if not apply:
                print(
                    "Auth identity migration is not applied. "
                    "Run with --apply to execute the migration."
                )
                return 2

            for statement in split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8")):
                await connection.exec_driver_sql(statement)
            verification_result = await connection.execute(AUTH_IDENTITY_STATUS_QUERY)
            verification = build_auth_identity_status(
                dict(verification_result.mappings().one())
            )
            if not verification.applied:
                print("Auth identity migration did not reach the expected schema state.")
                return 1

            print("Auth identity migration applied successfully.")
            return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect or apply the Logto external identity migration."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag, only a read-only preflight is run.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow apply against a non-local development database after review.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(apply=args.apply, allow_remote=args.allow_remote)))


if __name__ == "__main__":
    main()
