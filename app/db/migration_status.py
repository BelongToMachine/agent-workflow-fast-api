import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import text

from app.db.session import get_db_connection

MIGRATION_STATUS_QUERY = text(
    """
    SELECT
        to_regclass('public."KnowledgeBaseGrant"') IS NOT NULL AS grants_table,
        to_regclass('public."KnowledgeFile"') IS NOT NULL AS files_table,
        to_regclass('public."KnowledgeChunk"') IS NOT NULL AS chunks_table,
        EXISTS (
            SELECT 1
            FROM pg_extension
            WHERE extname = 'vector'
        ) AS vector_extension,
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'KnowledgeChunk'
              AND column_name = 'embedding'
        ) AS embedding_column,
        to_regclass('public."KnowledgeChunk_embedding_idx"') IS NOT NULL AS embedding_index,
        to_regclass('public."KnowledgeBase"') IS NOT NULL AS knowledge_base_table,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'KnowledgeBaseGrant_knowledge_base_entity_fk'
        ) AS grants_repointed,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'KnowledgeFile_knowledge_base_entity_fk'
        ) AS files_repointed,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'KnowledgeChunk_knowledge_base_entity_fk'
        ) AS chunks_repointed
    """
)


@dataclass(frozen=True)
class MigrationStatus:
    name: str
    applied: bool
    details: str


def build_migration_statuses(row: dict[str, object]) -> list[MigrationStatus]:
    grants_applied = bool(row["grants_table"])
    ingestion_applied = bool(row["files_table"]) and bool(row["chunks_table"])
    embeddings_applied = all(
        bool(row[key]) for key in ("vector_extension", "embedding_column", "embedding_index")
    )
    entity_applied = bool(row["knowledge_base_table"]) and all(
        bool(row[key]) for key in ("grants_repointed", "files_repointed", "chunks_repointed")
    )
    return [
        MigrationStatus(
            "0001_knowledge_base_grants",
            grants_applied,
            'KnowledgeBaseGrant table',
        ),
        MigrationStatus(
            "0002_knowledge_ingestion",
            ingestion_applied,
            'KnowledgeFile and KnowledgeChunk tables',
        ),
        MigrationStatus(
            "0003_knowledge_embeddings",
            embeddings_applied,
            'pgvector extension, embedding column, and HNSW index',
        ),
        MigrationStatus(
            "0004_knowledge_bases",
            entity_applied,
            'KnowledgeBase table and dependent foreign keys',
        ),
    ]


async def _run() -> int:
    async with get_db_connection() as connection:
        result = await connection.execute(MIGRATION_STATUS_QUERY)
        row = result.mappings().one()

    statuses = build_migration_statuses(dict(row))
    for status in statuses:
        state = "applied" if status.applied else "pending"
        print(f"{status.name}: {state} ({status.details})")
    return 0 if all(status.applied for status in statuses) else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect knowledge migration status.")
    parser.parse_args()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
