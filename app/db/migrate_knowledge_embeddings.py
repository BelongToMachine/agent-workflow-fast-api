import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_db_connection

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "0003_knowledge_embeddings.sql"
)
COLUMN_EXISTS_QUERY = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'KnowledgeChunk'
          AND column_name = 'embedding'
    ) AS column_exists
    """
)


async def _run(*, apply: bool) -> int:
    if not MIGRATION_PATH.is_file():
        print(f"Migration file not found: {MIGRATION_PATH}")
        return 1

    settings = get_settings()
    async with get_db_connection() as connection:
        async with connection.begin():
            result = await connection.execute(COLUMN_EXISTS_QUERY)
            if bool(result.scalar()):
                print("KnowledgeChunk.embedding is already present; nothing to do.")
                return 0

            if not apply:
                print(
                    "KnowledgeChunk.embedding is not present. "
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
            print("Knowledge embedding migration applied successfully.")
            return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage knowledge embedding storage.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag, only a read-only preflight is run.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(apply=args.apply)))


if __name__ == "__main__":
    main()
