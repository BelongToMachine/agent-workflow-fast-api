import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class KnowledgeSourceImport:
    """Stable metadata required to register an imported source file."""

    workspace_id: UUID
    display_name: str
    source_type: str
    file_hash: str | None = None
    storage_provider: str | None = None
    storage_key: str | None = None
    status: str = "ready"
    version: int = 1

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("A knowledge source display name is required.")
        if not self.source_type.strip():
            raise ValueError("A knowledge source type is required.")
        if self.version < 1:
            raise ValueError("A knowledge source version must be positive.")


SOURCE_UPSERT_QUERY = text(
    """
    INSERT INTO "KnowledgeSource"
        (
            "displayName", "fileHash", "id", "sourceType", "status",
            "storageKey", "storageProvider", "updatedAt", "version", "workspaceId"
        )
    VALUES
        (
            :display_name, :file_hash, :source_id, :source_type, :status,
            :storage_key, :storage_provider, CURRENT_TIMESTAMP, :version, :workspace_id
        )
    ON CONFLICT ("workspaceId", "fileHash")
        WHERE "fileHash" IS NOT NULL
    DO UPDATE SET
        "displayName" = EXCLUDED."displayName",
        "sourceType" = EXCLUDED."sourceType",
        "status" = EXCLUDED."status",
        "storageKey" = EXCLUDED."storageKey",
        "storageProvider" = EXCLUDED."storageProvider",
        "updatedAt" = CURRENT_TIMESTAMP,
        "version" = EXCLUDED."version"
    RETURNING "id"
    """
)


def sha256_file_content(content: bytes) -> str:
    """Return the stable hex hash used as the source import key."""

    return hashlib.sha256(content).hexdigest()


async def ensure_knowledge_source(
    connection: AsyncConnection,
    source: KnowledgeSourceImport,
) -> UUID:
    """Create or reuse a source row within the caller's transaction.

    A non-null file hash makes imports idempotent within a workspace. Sources
    without a hash are intentionally inserted as new rows for legacy/manual
    callers; file-based importers should always compute a hash first.
    """

    result = await connection.execute(
        SOURCE_UPSERT_QUERY,
        {
            "display_name": source.display_name.strip(),
            "file_hash": source.file_hash,
            "source_id": uuid4(),
            "source_type": source.source_type.strip(),
            "status": source.status,
            "storage_key": source.storage_key,
            "storage_provider": source.storage_provider,
            "version": source.version,
            "workspace_id": source.workspace_id,
        },
    )
    source_id = result.scalar_one()
    return UUID(str(source_id))


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
