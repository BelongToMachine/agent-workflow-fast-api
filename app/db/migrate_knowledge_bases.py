import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.db.migration_utils import migration_apply_error
from app.db.session import get_db_connection

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "0004_knowledge_bases.sql"
)
TABLE_EXISTS_QUERY = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'KnowledgeBase'
    ) AS table_exists
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
            result = await connection.execute(TABLE_EXISTS_QUERY)
            if bool(result.scalar()):
                print("KnowledgeBase is already present; nothing to do.")
                return 0

            if not apply:
                print(
                    "KnowledgeBase is not present. "
                    "Run with --apply to execute the migration."
                )
                return 2

            await connection.exec_driver_sql(MIGRATION_PATH.read_text(encoding="utf-8"))
            print("KnowledgeBase entity migration applied successfully.")
            return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the independent knowledge-base entity.")
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
