"""Apply the additive local authentication schema migration."""

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.db.local_auth_status import (
    LOCAL_AUTH_STATUS_QUERY,
    build_local_auth_status,
)
from app.db.migration_utils import migration_apply_error, split_sql_statements
from app.db.session import get_db_connection

MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "0010_local_auth.sql"


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
            status_result = await connection.execute(LOCAL_AUTH_STATUS_QUERY)
            status = build_local_auth_status(dict(status_result.mappings().one()))
            if status.applied:
                print("Local authentication migration is already applied; nothing to do.")
                return 0

            if not apply:
                print(
                    "Local authentication migration is not applied. "
                    "Run with --apply to execute the migration."
                )
                return 2

            for statement in split_sql_statements(MIGRATION_PATH.read_text(encoding="utf-8")):
                await connection.exec_driver_sql(statement)

            verification_result = await connection.execute(LOCAL_AUTH_STATUS_QUERY)
            verification = build_local_auth_status(
                dict(verification_result.mappings().one())
            )
            if not verification.applied:
                print("Local authentication migration did not reach the expected schema state.")
                return 1

            print("Local authentication migration applied successfully.")
            return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect or apply the local authentication schema migration."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag, only a read-only preflight is run.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow apply against a remote development database after backup and review.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(apply=args.apply, allow_remote=args.allow_remote)))


if __name__ == "__main__":
    main()
