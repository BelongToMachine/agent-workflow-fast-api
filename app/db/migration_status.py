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
        to_regclass('public."KnowledgeSource"') IS NOT NULL AS source_table,
        (
            SELECT COUNT(*) = 11
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'KnowledgeSource'
              AND column_name IN (
                  'createdAt', 'displayName', 'fileHash', 'id', 'sourceType',
                  'status', 'storageKey', 'storageProvider', 'updatedAt',
                  'version', 'workspaceId'
              )
        ) AS source_required_columns,
        to_regclass('public."KnowledgeSource_fileHash_idx"') IS NOT NULL
            AND to_regclass('public."KnowledgeSource_workspace_status_idx"') IS NOT NULL
            AS source_indexes,
        EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_record
            WHERE constraint_record.conrelid = to_regclass('public."KnowledgeSource"')
              AND constraint_record.contype = 'f'
              AND constraint_record.confrelid = to_regclass('public."Workspace"')
              AND constraint_record.conkey = ARRAY[
                  (
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."KnowledgeSource"')
                        AND attribute.attname = 'workspaceId'
                        AND NOT attribute.attisdropped
                  )
              ]::smallint[]
        ) AS source_workspace_fk,
        to_regclass('public."ContentRecord"') IS NOT NULL AS content_table,
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ContentRecord'
              AND column_name = 'sourceId'
        ) AS content_source_column,
        to_regclass('public."ContentRecord_sourceId_idx"') IS NOT NULL
            AS content_source_idx,
        to_regclass('public."ContentRecord_sourceId_sourceSheet_sourceRow_idx"') IS NOT NULL
            AS content_source_unique_idx,
        to_regclass('public."ContentRecord_sourceSheet_sourceRow_idx"') IS NULL
            AS content_legacy_unique_idx_removed,
        EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_record
            WHERE constraint_record.conrelid = to_regclass('public."ContentRecord"')
              AND constraint_record.contype = 'f'
              AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
              AND constraint_record.conkey = ARRAY[
                  (
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."ContentRecord"')
                        AND attribute.attname = 'sourceId'
                        AND NOT attribute.attisdropped
                  )
              ]::smallint[]
        ) AS content_source_fk,
        to_regclass('public."RealProductResearch"') IS NOT NULL AS research_table,
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'RealProductResearch'
              AND column_name = 'sourceId'
        ) AS research_source_column,
        to_regclass('public."RealProductResearch_sourceId_idx"') IS NOT NULL
            AS research_source_idx,
        to_regclass('public."RealProductResearch_sourceId_sourceSheet_sourceRow_idx"') IS NOT NULL
            AS research_source_unique_idx,
        to_regclass('public."RealProductResearch_sourceSheet_sourceRow_idx"') IS NULL
            AS research_legacy_unique_idx_removed,
        EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_record
            WHERE constraint_record.conrelid = to_regclass('public."RealProductResearch"')
              AND constraint_record.contype = 'f'
              AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
              AND constraint_record.conkey = ARRAY[
                  (
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."RealProductResearch"')
                        AND attribute.attname = 'sourceId'
                        AND NOT attribute.attisdropped
                  )
              ]::smallint[]
        ) AS research_source_fk,
        NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ContentRecord'
              AND column_name = 'sourceId'
              AND is_nullable = 'YES'
        ) AS content_source_non_null,
        NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'RealProductResearch'
              AND column_name = 'sourceId'
              AND is_nullable = 'YES'
        ) AS research_source_non_null,
        to_regclass('public."ProductDocument"') IS NOT NULL AS document_table,
        EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ProductDocument'
              AND column_name = 'sourceId'
        ) AS document_source_column,
        to_regclass('public."ProductDocument_sourceId_idx"') IS NOT NULL
            AS document_source_idx,
        EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_record
            WHERE constraint_record.conrelid = to_regclass('public."ProductDocument"')
              AND constraint_record.contype = 'f'
              AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
              AND constraint_record.conkey = ARRAY[
                  (
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."ProductDocument"')
                        AND attribute.attname = 'sourceId'
                        AND NOT attribute.attisdropped
                  )
              ]::smallint[]
        ) AS document_source_fk,
        NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'ProductDocument'
              AND column_name = 'sourceId'
              AND is_nullable = 'YES'
        ) AS document_source_non_null,
        EXISTS (
            SELECT 1
            FROM pg_index AS index_record
            WHERE index_record.indexrelid = to_regclass(
                'public."KnowledgeSource_workspace_fileHash_unique_idx"'
            )
              AND index_record.indisunique
        ) AS source_import_key_idx,
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

    source_applied = all(
        flag(key)
        for key in (
            "source_table",
            "source_required_columns",
            "source_indexes",
            "source_workspace_fk",
        )
    )
    source_relationships_applied = all(
        flag(key)
        for key in (
            "content_table",
            "content_source_column",
            "content_source_idx",
            "content_source_unique_idx",
            "content_legacy_unique_idx_removed",
            "content_source_fk",
            "research_table",
            "research_source_column",
            "research_source_idx",
            "research_source_unique_idx",
            "research_legacy_unique_idx_removed",
            "research_source_fk",
            "document_table",
            "document_source_column",
            "document_source_idx",
            "document_source_fk",
        )
    )
    source_import_key_applied = flag("source_import_key_idx")
    source_relationships_required = all(
        flag(key)
        for key in (
            "content_source_non_null",
            "research_source_non_null",
            "document_source_non_null",
        )
    )
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
        MigrationStatus(
            "0006_knowledge_source_provenance",
            source_applied,
            "KnowledgeSource columns, workspace foreign key, and indexes",
        ),
        MigrationStatus(
            "0007_knowledge_source_relationships",
            source_relationships_applied,
            "sourceId foreign keys, indexes, and source-scoped row uniqueness",
        ),
        MigrationStatus(
            "0008_knowledge_source_import_key",
            source_import_key_applied,
            "workspace-scoped unique KnowledgeSource fileHash import key",
        ),
        MigrationStatus(
            "0009_knowledge_source_relationships_required",
            source_relationships_required,
            "non-null sourceId columns after legacy provenance backfill",
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
