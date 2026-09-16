import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class KnowledgeFileImport:
    """Stable metadata required to register an imported source file.

    KnowledgeBase is the container; KnowledgeFile is the canonical source
    record. ``knowledge_base_id`` is optional only for old seed payloads that
    target a workspace with exactly one ready knowledge base.
    """

    workspace_id: UUID
    display_name: str
    source_type: str
    knowledge_base_id: UUID | None = None
    file_hash: str | None = None
    storage_provider: str | None = None
    storage_key: str | None = None
    status: str = "ready"
    version: int = 1
    byte_size: int = 0
    mime_type: str | None = None
    uploaded_by: UUID | None = None

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("A knowledge file display name is required.")
        if not self.source_type.strip():
            raise ValueError("A knowledge file type is required.")
        if self.version < 1:
            raise ValueError("A knowledge file version must be positive.")
        if self.byte_size < 0:
            raise ValueError("A knowledge file size cannot be negative.")


# Backward-compatible import name for callers that still use the old seed
# vocabulary. New code should use KnowledgeFileImport.
KnowledgeSourceImport = KnowledgeFileImport


FILE_UPSERT_QUERY = text(
    """
    INSERT INTO "KnowledgeFile"
        (
            "byteSize", "fileHash", "id", "knowledgeBaseId", "mimeType",
            "originalName", "status", "storageKey", "storageProvider",
            "uploadedBy", "workspaceId"
        )
    VALUES
        (
            :byte_size, :file_hash, :file_id, :knowledge_base_id, :mime_type,
            :display_name, :status, :storage_key, :storage_provider,
            :uploaded_by, :workspace_id
        )
    ON CONFLICT ("knowledgeBaseId", "fileHash")
    DO UPDATE SET
        "byteSize" = EXCLUDED."byteSize",
        "mimeType" = EXCLUDED."mimeType",
        "originalName" = EXCLUDED."originalName",
        "status" = EXCLUDED."status",
        "storageKey" = EXCLUDED."storageKey",
        "storageProvider" = EXCLUDED."storageProvider",
        "updatedAt" = CURRENT_TIMESTAMP
    RETURNING "id"
    """
)

SOURCE_UPSERT_QUERY = FILE_UPSERT_QUERY

KNOWLEDGE_BASE_FOR_FILE_QUERY = text(
    """
    SELECT "id"
    FROM "KnowledgeBase"
    WHERE "workspaceId" = :workspace_id
      AND "status" = 'ready'
      AND (CAST(:knowledge_base_id AS uuid) IS NULL OR "id" = :knowledge_base_id)
    ORDER BY "createdAt" ASC
    """
)

UPLOADER_QUERY = text(
    """
    SELECT COALESCE(
        (
            SELECT "ownerId"
            FROM "Workspace"
            WHERE "id" = :workspace_id
              AND "ownerId" IS NOT NULL
        ),
        (
            SELECT member."userId"
            FROM "WorkspaceMember" AS member
            WHERE member."workspaceId" = :workspace_id
              AND member."status" = 'active'
            ORDER BY member."createdAt" ASC
            LIMIT 1
        )
    ) AS uploaded_by
    """
)

MIME_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "pdf": "application/pdf",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def sha256_file_content(content: bytes) -> str:
    """Return the stable hex hash used as the source import key."""

    return hashlib.sha256(content).hexdigest()


async def ensure_knowledge_file(
    connection: AsyncConnection,
    source: KnowledgeFileImport,
) -> UUID:
    """Create or reuse a canonical KnowledgeFile row.

    File hashes make imports idempotent within a knowledge base. The fallback
    to the sole ready KnowledgeBase exists only for old seed payloads; new
    callers should always send knowledge_base_id explicitly.
    """
    if not source.file_hash:
        raise ValueError("A knowledge file hash is required for an import.")
    if len(source.file_hash) > 64:
        raise ValueError("A knowledge file hash must be at most 64 characters.")

    base_result = await connection.execute(
        KNOWLEDGE_BASE_FOR_FILE_QUERY,
        {
            "knowledge_base_id": source.knowledge_base_id,
            "workspace_id": source.workspace_id,
        },
    )
    knowledge_base_ids = [row[0] for row in base_result]
    if len(knowledge_base_ids) != 1:
        if not knowledge_base_ids:
            raise ValueError(
                "The import does not reference an existing ready KnowledgeBase."
            )
        raise ValueError(
            "knowledgeBaseId is required when a workspace has multiple ready knowledge bases."
        )
    knowledge_base_id = UUID(str(knowledge_base_ids[0]))

    uploaded_by = source.uploaded_by
    if uploaded_by is None:
        uploader_result = await connection.execute(
            UPLOADER_QUERY,
            {"workspace_id": source.workspace_id},
        )
        uploaded_by = uploader_result.scalar_one_or_none()
    if uploaded_by is None:
        raise ValueError("The import workspace has no user available as uploadedBy.")

    source_type = source.source_type.strip().lower().lstrip(".")
    mime_type = source.mime_type or MIME_TYPES.get(
        source_type,
        "application/octet-stream",
    )
    storage_provider = (source.storage_provider or "local").strip().lower()
    storage_key = source.storage_key or (
        f"imports/{source.workspace_id}/{knowledge_base_id}/{source.file_hash}"
    )

    result = await connection.execute(
        FILE_UPSERT_QUERY,
        {
            "byte_size": source.byte_size,
            "display_name": source.display_name.strip(),
            "file_hash": source.file_hash,
            "file_id": uuid4(),
            "knowledge_base_id": knowledge_base_id,
            "mime_type": mime_type,
            "original_name": source.display_name.strip(),
            "status": source.status,
            "storage_key": storage_key,
            "storage_provider": storage_provider,
            "uploaded_by": uploaded_by,
            "workspace_id": source.workspace_id,
        },
    )
    file_id = result.scalar_one()
    return UUID(str(file_id))


async def ensure_knowledge_source(
    connection: AsyncConnection,
    source: KnowledgeSourceImport,
) -> UUID:
    """Deprecated alias for ensure_knowledge_file."""

    return await ensure_knowledge_file(connection, source)


def attach_file_provenance(
    record: Mapping[str, Any],
    *,
    source_file_id: UUID,
    source_sheet: str,
    source_row: int,
) -> dict[str, Any]:
    """Attach canonical KnowledgeFile provenance to an imported row."""

    return {
        **attach_source_coordinates(
            record,
            source_sheet=source_sheet,
            source_row=source_row,
        ),
        "sourceFileId": source_file_id,
    }


def attach_source_provenance(
    record: Mapping[str, Any],
    *,
    source_id: UUID,
    source_sheet: str,
    source_row: int,
) -> dict[str, Any]:
    """Return an imported row with authoritative source provenance attached."""

    return {
        **attach_source_coordinates(
            record,
            source_sheet=source_sheet,
            source_row=source_row,
        ),
        "sourceId": source_id,
    }


def attach_source_coordinates(
    record: Mapping[str, Any],
    *,
    source_sheet: str,
    source_row: int,
) -> dict[str, Any]:
    normalized_sheet = source_sheet.strip()
    if not normalized_sheet:
        raise ValueError("A source sheet or section is required.")
    if source_row < 1:
        raise ValueError("A source row must be a positive integer.")

    return {
        **record,
        "sourceSheet": normalized_sheet,
        "sourceRow": source_row,
    }
