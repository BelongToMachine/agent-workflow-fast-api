import argparse
import asyncio
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.business_table_mock import build_product_price_mock_seed
from app.db.knowledge_seed import _assert_migrations_ready, seed_sections
from app.db.migration_utils import migration_apply_error
from app.db.session import get_db_connection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed synthetic ProductPrice rows for the business data table preview."
    )
    parser.add_argument(
        "--knowledge-base-id",
        type=UUID,
        help="Ready KnowledgeBase in the configured default workspace.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow writes to a reviewed non-local development database.",
    )
    return parser


async def run_cli() -> int:
    args = _parser().parse_args()
    settings = get_settings()
    if error := migration_apply_error(settings, allow_remote=args.allow_remote):
        print(error)
        return 1

    try:
        async with get_db_connection() as connection:
            if args.knowledge_base_id is None:
                result = await connection.execute(
                    text(
                        """
                        SELECT "id"
                        FROM "KnowledgeBase"
                        WHERE "workspaceId" = :workspace_id
                          AND "status" = 'ready'
                        ORDER BY "createdAt", "id"
                        """
                    ),
                    {"workspace_id": settings.default_workspace_id},
                )
                knowledge_base_ids = [UUID(str(row[0])) for row in result]
                if len(knowledge_base_ids) != 1:
                    print(
                        "Pass --knowledge-base-id because the configured workspace "
                        "does not have exactly one ready knowledge base."
                    )
                    return 1
                knowledge_base_id = knowledge_base_ids[0]
            else:
                knowledge_base_id = args.knowledge_base_id

            source, sections = build_product_price_mock_seed(
                settings.default_workspace_id,
                knowledge_base_id,
            )
            async with connection.begin():
                await _assert_migrations_ready(connection)
                source_file_id, counts = await seed_sections(connection, source, sections)
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        print(f"Mock ProductPrice seed failed: {error}")
        return 1

    print(f"Mock source file: {source_file_id}")
    print(f"Ready product records: {counts.real_product_research}")
    print(f"Mock ProductPrice records: {counts.product_prices}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run_cli()))


if __name__ == "__main__":
    main()
