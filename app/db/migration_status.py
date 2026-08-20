import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import text

from app.db.auth_identity_status import (
    AUTH_IDENTITY_STATUS_QUERY,
    build_auth_identity_status,
)
from app.db.session import get_db_connection

MIGRATION_STATUS_QUERY = text(
    """
    SELECT
        to_regclass('public."KnowledgeBaseGrant"') IS NOT NULL AS grants_table,
        (
            SELECT COUNT(*) = 8
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'KnowledgeBaseGrant'
              AND column_name IN (
                  'accessLevel', 'createdAt', 'id', 'knowledgeBaseId',
                  'subjectId', 'subjectType', 'updatedAt', 'workspaceId'
              )
        ) AS grants_required_columns,
        to_regclass('public."KnowledgeBaseGrant_workspace_subject_idx"') IS NOT NULL
            AND to_regclass('public."KnowledgeBaseGrant_knowledge_base_idx"') IS NOT NULL
            AS grants_indexes,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeBaseGrant"')
              AND conname = 'KnowledgeBaseGrant_workspace_fk'
        ) AS grants_workspace_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeBaseGrant"')
              AND conname IN (
                  'KnowledgeBaseGrant_knowledge_base_fk',
                  'KnowledgeBaseGrant_knowledge_base_entity_fk'
              )
        ) AS grants_knowledge_base_fk,
        to_regclass('public."KnowledgeFile"') IS NOT NULL AS files_table,
        (
            SELECT COUNT(*) = 14
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'KnowledgeFile'
              AND column_name IN (
                  'byteSize', 'createdAt', 'errorMessage', 'fileHash', 'id',
                  'knowledgeBaseId', 'mimeType', 'originalName', 'status',
                  'storageKey', 'storageProvider', 'updatedAt', 'uploadedBy',
                  'workspaceId'
              )
        ) AS files_required_columns,
        to_regclass('public."KnowledgeFile_workspace_idx"') IS NOT NULL
            AS files_indexes,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeFile"')
              AND conname IN (
                  'KnowledgeFile_knowledge_base_fk',
                  'KnowledgeFile_knowledge_base_entity_fk'
              )
        ) AS files_knowledge_base_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeFile"')
              AND conname = 'KnowledgeFile_uploaded_by_fk'
        ) AS files_uploaded_by_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeFile"')
              AND conname = 'KnowledgeFile_workspace_fk'
        ) AS files_workspace_fk,
        to_regclass('public."KnowledgeChunk"') IS NOT NULL AS chunks_table,
        (
            SELECT COUNT(*) = 8
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'KnowledgeChunk'
              AND column_name IN (
                  'chunkIndex', 'content', 'createdAt', 'fileId', 'id',
                  'knowledgeBaseId', 'metadata', 'workspaceId'
              )
        ) AS chunks_required_columns,
        to_regclass('public."KnowledgeChunk_lookup_idx"') IS NOT NULL
            AS chunks_indexes,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeChunk"')
              AND conname = 'KnowledgeChunk_file_fk'
        ) AS chunks_file_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeChunk"')
              AND conname IN (
                  'KnowledgeChunk_knowledge_base_fk',
                  'KnowledgeChunk_knowledge_base_entity_fk'
              )
        ) AS chunks_knowledge_base_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeChunk"')
              AND conname = 'KnowledgeChunk_workspace_fk'
        ) AS chunks_workspace_fk,
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
        EXISTS (
            SELECT 1
            FROM pg_index AS index_record
            INNER JOIN pg_class AS index_relation
                ON index_relation.oid = index_record.indexrelid
            INNER JOIN pg_am AS access_method
                ON access_method.oid = index_relation.relam
            WHERE index_record.indexrelid = to_regclass('public."KnowledgeChunk_embedding_idx"')
              AND index_record.indisvalid
              AND access_method.amname = 'hnsw'
        ) AS embedding_index_valid,
        to_regclass('public."KnowledgeBase"') IS NOT NULL AS knowledge_base_table,
        (
            SELECT COUNT(*) = 10
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'KnowledgeBase'
              AND column_name IN (
                  'createdAt', 'displayName', 'fileHash', 'id', 'sourceType',
                  'status', 'storageProvider', 'updatedAt', 'version', 'workspaceId'
              )
        ) AS knowledge_base_required_columns,
        to_regclass('public."KnowledgeBase_workspace_status_idx"') IS NOT NULL
            AND to_regclass('public."KnowledgeBase_workspace_name_idx"') IS NOT NULL
            AS knowledge_base_indexes,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeBase"')
              AND conname = 'KnowledgeBase_workspace_fk'
        ) AS knowledge_base_workspace_fk,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeBaseGrant"')
              AND conname = 'KnowledgeBaseGrant_knowledge_base_entity_fk'
        ) AS grants_repointed,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeFile"')
              AND conname = 'KnowledgeFile_knowledge_base_entity_fk'
        ) AS files_repointed,
        EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = to_regclass('public."KnowledgeChunk"')
              AND conname = 'KnowledgeChunk_knowledge_base_entity_fk'
        ) AS chunks_repointed
    """
)


@dataclass(frozen=True)
class MigrationStatus:
    name: str
    applied: bool
    details: str


def build_migration_statuses(row: dict[str, object]) -> list[MigrationStatus]:
    def flag(name: str) -> bool:
        return bool(row.get(name, False))

    grants_applied = all(
        flag(key)
        for key in (
            "grants_table",
            "grants_required_columns",
            "grants_indexes",
            "grants_workspace_fk",
            "grants_knowledge_base_fk",
        )
    )
    ingestion_applied = all(
        flag(key)
        for key in (
            "files_table",
            "files_required_columns",
            "files_indexes",
            "files_knowledge_base_fk",
            "files_uploaded_by_fk",
            "files_workspace_fk",
            "chunks_table",
            "chunks_required_columns",
            "chunks_indexes",
            "chunks_file_fk",
            "chunks_knowledge_base_fk",
            "chunks_workspace_fk",
        )
    )
    embeddings_applied = all(
        flag(key)
        for key in (
            "vector_extension",
            "embedding_column",
            "embedding_index",
            "embedding_index_valid",
        )
    )
    entity_applied = all(
        flag(key)
        for key in (
            "knowledge_base_table",
            "knowledge_base_required_columns",
            "knowledge_base_indexes",
            "knowledge_base_workspace_fk",
            "grants_repointed",
            "files_repointed",
            "chunks_repointed",
        )
    )
    return [
        MigrationStatus(
            "0001_knowledge_base_grants",
            grants_applied,
            "KnowledgeBaseGrant table, columns, indexes, and foreign keys",
        ),
        MigrationStatus(
            "0002_knowledge_ingestion",
            ingestion_applied,
            "KnowledgeFile and KnowledgeChunk tables, columns, indexes, and foreign keys",
        ),
        MigrationStatus(
            "0003_knowledge_embeddings",
            embeddings_applied,
            "pgvector extension, vector(1536) embedding column, and valid HNSW index",
        ),
        MigrationStatus(
            "0004_knowledge_bases",
            entity_applied,
            "KnowledgeBase table, indexes, and dependent foreign keys",
        ),
    ]


async def _run() -> int:
    async with get_db_connection() as connection:
        result = await connection.execute(MIGRATION_STATUS_QUERY)
        row = result.mappings().one()
        auth_result = await connection.execute(AUTH_IDENTITY_STATUS_QUERY)
        auth_row = auth_result.mappings().one()

    statuses = build_migration_statuses(dict(row))
    auth_status = build_auth_identity_status(dict(auth_row))
    statuses.append(
        MigrationStatus(
            auth_status.name,
            auth_status.applied,
            auth_status.details,
        )
    )
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
