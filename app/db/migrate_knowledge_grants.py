import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_db_connection

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "0001_knowledge_base_grants.sql"
)
TABLE_EXISTS_QUERY = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'KnowledgeBaseGrant'
    ) AS table_exists
    """
)


async def _run(*, apply: bool) -> int:
    if not MIGRATION_PATH.is_file():
        print(f"Migration file not found: {MIGRATION_PATH}")
        return 1

    settings = get_settings()
    async with get_db_connection() as connection:
        async with connection.begin():
            result = await connection.execute(TABLE_EXISTS_QUERY)
            table_exists = bool(result.scalar())
            if table_exists:
                print('KnowledgeBaseGrant is already present; nothing to do.')
                return 0

            if not apply:
                print(
                    "KnowledgeBaseGrant is not present. "
                    "Run with --apply to execute the migration."
                )
                return 2

            if settings.environment.lower() in {"production", "staging"}:
                print(
                    "Refusing to apply a local migration in staging/production. "
                    "Run the reviewed SQL through the deployment migration process."
                )
                return 1

            await connection.exec_driver_sql(MIGRATION_PATH.read_text(encoding="utf-8"))
            print("KnowledgeBaseGrant migration applied successfully.")
            return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the transitional knowledge grants table.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag, only a read-only preflight is run.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(apply=args.apply)))


if __name__ == "__main__":
    main()
