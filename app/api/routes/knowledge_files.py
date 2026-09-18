import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.knowledge_access import require_knowledge_base_permission
from app.db.errors import DatabaseServiceError
from app.db.session import get_db_connection
from app.services.document_parsing import (
    FILE_SIGNATURES,
    SUPPORTED_EXTENSIONS,
    ParsedDocument,
    paginate_parsed_document,
    parse_document,
    render_document_text,
)
from app.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    embed_texts,
    vector_literal,
)
from app.services.storage import (
    LocalKnowledgeStorage,
    StorageConfigurationError,
    StorageError,
    get_knowledge_storage,
    get_knowledge_storage_for_provider,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])

SAFE_FILENAME_PATTERN = re.compile(r"[^\w.-]+")
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 120
logger = logging.getLogger(__name__)


class KnowledgeFileSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    byte_size: int = Field(alias="byteSize")
    created_at: str = Field(alias="createdAt")
    error_message: str | None = Field(default=None, alias="errorMessage")
    file_hash: str = Field(alias="fileHash")
    file_id: str = Field(alias="fileId")
    knowledge_base_id: str = Field(alias="knowledgeBaseId")
    mime_type: str = Field(alias="mimeType")
    original_name: str = Field(alias="originalName")
    status: str
    storage_provider: str = Field(alias="storageProvider")
    updated_at: str = Field(alias="updatedAt")
    workspace_id: str = Field(alias="workspaceId")


class KnowledgeFileListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    files: list[KnowledgeFileSummary]


class KnowledgeParsedDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chunk_count: int = Field(alias="chunkCount")
    chunk_error_message: str | None = Field(
        default=None,
        alias="chunkErrorMessage",
    )
    chunk_status: str = Field(alias="chunkStatus")
    created_at: str = Field(alias="createdAt")
    parsed_document: ParsedDocument = Field(alias="parsedDocument")
    parsed_document_id: str = Field(alias="parsedDocumentId")
    updated_at: str = Field(alias="updatedAt")


class KnowledgeParsedDocumentListItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chunk_count: int = Field(alias="chunkCount")
    embedded_chunk_count: int = Field(alias="embeddedChunkCount")
    chunk_error_message: str | None = Field(
        default=None,
        alias="chunkErrorMessage",
    )
    chunk_status: str = Field(alias="chunkStatus")
    created_at: str = Field(alias="createdAt")
    file_byte_size: int = Field(alias="fileByteSize")
    file_hash: str = Field(alias="fileHash")
    file_id: str = Field(alias="fileId")
    file_mime_type: str = Field(alias="fileMimeType")
    file_name: str = Field(alias="fileName")
    file_status: str = Field(alias="fileStatus")
    parsed_document: ParsedDocument = Field(alias="parsedDocument")
    parsed_document_id: str = Field(alias="parsedDocumentId")
    updated_at: str = Field(alias="updatedAt")


class KnowledgeParsedDocumentListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[KnowledgeParsedDocumentListItem]
    limit: int
    next_offset: int | None = Field(alias="nextOffset")
    offset: int
    total: int


class KnowledgeChunkSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chunk_id: str = Field(alias="chunkId")
    chunk_index: int = Field(alias="chunkIndex")
    content: str
    embedding_model: str | None = Field(alias="embeddingModel")
    is_embedded: bool = Field(alias="isEmbedded")


class KnowledgeChunkListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[KnowledgeChunkSummary]
    limit: int
    next_offset: int | None = Field(alias="nextOffset")
    offset: int
    total: int


class KnowledgeChunkEmbeddingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chunk_ids: list[UUID] = Field(alias="chunkIds", min_length=1, max_length=100)

    @field_validator("chunk_ids")
    @classmethod
    def reject_duplicate_chunk_ids(cls, chunk_ids: list[UUID]) -> list[UUID]:
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("chunkIds must not contain duplicate IDs.")
        return chunk_ids


class KnowledgeChunkEmbeddingResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dimensions: int
    embedded_count: int = Field(alias="embeddedCount")
    embedding_model: str = Field(alias="embeddingModel")


FILE_SELECT = text(
    """
    SELECT
        "byteSize" AS byte_size,
        "createdAt" AS created_at,
        "errorMessage" AS error_message,
        "fileHash" AS file_hash,
        "id" AS file_id,
        "knowledgeBaseId" AS knowledge_base_id,
        "mimeType" AS mime_type,
        "originalName" AS original_name,
        "status" AS status,
        "storageProvider" AS storage_provider,
        "storageKey" AS storage_key,
        "updatedAt" AS updated_at,
        "workspaceId" AS workspace_id
    FROM "KnowledgeFile"
    """
)

FILE_BY_ID_QUERY = text(
    FILE_SELECT.text
    + """
    WHERE "id" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

FILE_PROCESS_QUERY = text(
    FILE_SELECT.text
    + """
    WHERE "id" = :file_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

FILE_LIST_QUERY = text(
    FILE_SELECT.text
    + """
    WHERE "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    ORDER BY "createdAt" DESC
    """
)

FILE_INSERT_QUERY = text(
    """
    INSERT INTO "KnowledgeFile"
        (
            "byteSize", "fileHash", "id", "knowledgeBaseId", "mimeType",
            "originalName", "storageKey", "storageProvider", "uploadedBy", "workspaceId"
        )
    VALUES
        (
            :byte_size, :file_hash, :file_id, :knowledge_base_id, :mime_type,
            :original_name, :storage_key, :storage_provider, :uploaded_by, :workspace_id
        )
    ON CONFLICT ("knowledgeBaseId", "fileHash") DO NOTHING
    RETURNING "id"
    """
)

FILE_STATUS_QUERY = text(
    """
    UPDATE "KnowledgeFile"
    SET "errorMessage" = :error_message,
        "status" = :status,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :file_id
      AND "workspaceId" = :workspace_id
    """
)

FILE_PARSE_CLAIM_QUERY = text(
    """
    UPDATE "KnowledgeFile"
    SET "errorMessage" = NULL,
        "status" = 'processing',
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
      AND "status" <> 'processing'
    RETURNING "id"
    """
)

PARSED_DOCUMENT_SELECT = text(
    """
    SELECT
        "blockCount" AS block_count,
        "chunkErrorMessage" AS chunk_error_message,
        "chunkStatus" AS chunk_status,
        "createdAt" AS created_at,
        "document" AS document,
        "fileHash" AS file_hash,
        "fileId" AS file_id,
        "id" AS parsed_document_id,
        "knowledgeBaseId" AS knowledge_base_id,
        "parser" AS parser,
        "parserVersion" AS parser_version,
        "schemaVersion" AS schema_version,
        "updatedAt" AS updated_at,
        "warningCount" AS warning_count,
        "workspaceId" AS workspace_id
    FROM "KnowledgeParsedDocument"
    """
)

PARSED_DOCUMENT_BY_FILE_QUERY = text(
    PARSED_DOCUMENT_SELECT.text
    + """
    WHERE "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

PARSED_DOCUMENT_LIST_QUERY = text(
    """
    SELECT
        parsed."blockCount" AS block_count,
        (
            SELECT COUNT(*)
            FROM "KnowledgeChunk" AS chunk
            WHERE chunk."fileId" = parsed."fileId"
              AND chunk."knowledgeBaseId" = parsed."knowledgeBaseId"
              AND chunk."workspaceId" = parsed."workspaceId"
        ) AS chunk_count,
        (
            SELECT COUNT(*)
            FROM "KnowledgeChunk" AS chunk
            WHERE chunk."fileId" = parsed."fileId"
              AND chunk."knowledgeBaseId" = parsed."knowledgeBaseId"
              AND chunk."workspaceId" = parsed."workspaceId"
              AND chunk."embedding" IS NOT NULL
        ) AS embedded_chunk_count,
        parsed."chunkErrorMessage" AS chunk_error_message,
        parsed."chunkStatus" AS chunk_status,
        parsed."createdAt" AS created_at,
        parsed."document" AS document,
        parsed."fileHash" AS file_hash,
        parsed."fileId" AS file_id,
        parsed."id" AS parsed_document_id,
        parsed."updatedAt" AS updated_at,
        file."byteSize" AS file_byte_size,
        file."mimeType" AS file_mime_type,
        file."originalName" AS file_name,
        file."status" AS file_status
    FROM "KnowledgeParsedDocument" AS parsed
    INNER JOIN "KnowledgeFile" AS file ON file."id" = parsed."fileId"
    WHERE parsed."knowledgeBaseId" = :knowledge_base_id
      AND parsed."workspaceId" = :workspace_id
    ORDER BY parsed."updatedAt" DESC, parsed."id" DESC
    LIMIT :limit OFFSET :offset
    """
)

PARSED_DOCUMENT_COUNT_QUERY = text(
    """
    SELECT COUNT(*) AS document_count
    FROM "KnowledgeParsedDocument" AS parsed
    WHERE parsed."knowledgeBaseId" = :knowledge_base_id
      AND parsed."workspaceId" = :workspace_id
    """
)

PARSED_DOCUMENT_UPSERT_QUERY = text(
    """
    INSERT INTO "KnowledgeParsedDocument"
        (
            "blockCount", "chunkErrorMessage", "chunkStatus", "contentType",
            "document", "fileHash", "fileId", "knowledgeBaseId", "parser",
            "parserVersion", "schemaVersion", "warningCount", "workspaceId"
        )
    VALUES
        (
            :block_count, NULL, 'pending', :content_type,
            CAST(:document AS jsonb), :file_hash, :file_id, :knowledge_base_id,
            :parser, :parser_version, :schema_version, :warning_count, :workspace_id
        )
    ON CONFLICT ("fileId") DO UPDATE SET
        "blockCount" = EXCLUDED."blockCount",
        "chunkErrorMessage" = NULL,
        "chunkStatus" = 'pending',
        "chunkedAt" = NULL,
        "contentType" = EXCLUDED."contentType",
        "document" = EXCLUDED."document",
        "fileHash" = EXCLUDED."fileHash",
        "knowledgeBaseId" = EXCLUDED."knowledgeBaseId",
        "parser" = EXCLUDED."parser",
        "parserVersion" = EXCLUDED."parserVersion",
        "schemaVersion" = EXCLUDED."schemaVersion",
        "warningCount" = EXCLUDED."warningCount",
        "updatedAt" = CURRENT_TIMESTAMP,
        "workspaceId" = EXCLUDED."workspaceId"
    """
)

PARSED_DOCUMENT_CHUNK_CLAIM_QUERY = text(
    """
    UPDATE "KnowledgeParsedDocument"
    SET "chunkErrorMessage" = NULL,
        "chunkStatus" = 'processing',
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :parsed_document_id
      AND "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
      AND "chunkStatus" <> 'processing'
    RETURNING "id"
    """
)

PARSED_DOCUMENT_CHUNK_STATUS_QUERY = text(
    """
    UPDATE "KnowledgeParsedDocument"
    SET "chunkErrorMessage" = CAST(:chunk_error_message AS text),
        "chunkStatus" = CAST(:chunk_status AS varchar(16)),
        "chunkedAt" = CASE
            WHEN CAST(:chunk_status AS varchar(16)) = CAST('ready' AS varchar(16))
            THEN CURRENT_TIMESTAMP
            ELSE NULL
        END,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :parsed_document_id
      AND "fileId" = :file_id
      AND "workspaceId" = :workspace_id
    """
)

CHUNK_COUNT_BY_FILE_QUERY = text(
    """
    SELECT COUNT(*) AS chunk_count
    FROM "KnowledgeChunk"
    WHERE "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    """
)

CHUNK_LIST_BY_FILE_QUERY = text(
    """
    SELECT
        "id" AS chunk_id,
        "chunkIndex" AS chunk_index,
        "content" AS content,
        ("embedding" IS NOT NULL) AS is_embedded,
        "embeddingModel" AS embedding_model
    FROM "KnowledgeChunk"
    WHERE "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    ORDER BY "chunkIndex" ASC, "id" ASC
    LIMIT :limit OFFSET :offset
    """
)

CHUNKS_SELECT_FOR_EMBEDDING_QUERY = text(
    """
    SELECT "id" AS chunk_id, "content" AS content
    FROM "KnowledgeChunk"
    WHERE "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
      AND "id" = ANY(CAST(:chunk_ids AS uuid[]))
    ORDER BY "chunkIndex" ASC, "id" ASC
    """
)

CHUNKS_SELECT_FOR_ALL_EMBEDDING_QUERY = text(
    """
    SELECT "id" AS chunk_id, "content" AS content
    FROM "KnowledgeChunk"
    WHERE "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
      AND (
          "embedding" IS NULL
          OR "embeddingModel" IS DISTINCT FROM :embedding_model
      )
    ORDER BY "chunkIndex" ASC, "id" ASC
    """
)

CHUNK_EMBEDDING_UPDATE_QUERY = text(
    """
    UPDATE "KnowledgeChunk"
    SET "embedding" = CAST(:embedding AS vector(1024)),
        "embeddingModel" = :embedding_model
    WHERE "id" = :chunk_id
      AND "fileId" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    RETURNING "id"
    """
)

CHUNKS_DELETE_QUERY = text('DELETE FROM "KnowledgeChunk" WHERE "fileId" = :file_id')
CHUNKS_INSERT_QUERY = text(
    """
    INSERT INTO "KnowledgeChunk"
        ("chunkIndex", "content", "fileId", "knowledgeBaseId", "metadata", "workspaceId")
    VALUES
        (
            :chunk_index,
            :content,
            :file_id,
            :knowledge_base_id,
            CAST(:metadata AS jsonb),
            :workspace_id
        )
    """
)

FILE_DELETE_QUERY = text(
    """
    DELETE FROM "KnowledgeFile"
    WHERE "id" = :file_id
      AND "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    RETURNING "storageKey", "storageProvider"
    """
)


def _iso_timestamp(value: object) -> str:
    from datetime import UTC, datetime

    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_summary(row: dict[str, object]) -> KnowledgeFileSummary:
    return KnowledgeFileSummary(
        byteSize=int(row["byte_size"]),
        createdAt=_iso_timestamp(row["created_at"]),
        errorMessage=row["error_message"] if isinstance(row["error_message"], str) else None,
        fileHash=str(row["file_hash"]),
        fileId=str(row["file_id"]),
        knowledgeBaseId=str(row["knowledge_base_id"]),
        mimeType=str(row["mime_type"]),
        originalName=str(row["original_name"]),
        status=str(row["status"]),
        storageProvider=str(row["storage_provider"]),
        updatedAt=_iso_timestamp(row["updated_at"]),
        workspaceId=str(row["workspace_id"]),
    )


def _parsed_document_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _parsed_document_response(
    row: dict[str, object],
    chunk_count: int,
) -> KnowledgeParsedDocumentResponse:
    return KnowledgeParsedDocumentResponse(
        chunkCount=chunk_count,
        chunkErrorMessage=(
            row["chunk_error_message"]
            if isinstance(row.get("chunk_error_message"), str)
            else None
        ),
        chunkStatus=str(row["chunk_status"]),
        createdAt=_iso_timestamp(row["created_at"]),
        parsedDocument=ParsedDocument.model_validate(
            _parsed_document_value(row["document"])
        ),
        parsedDocumentId=str(row["parsed_document_id"]),
        updatedAt=_iso_timestamp(row["updated_at"]),
    )


def _parsed_document_list_item(
    row: dict[str, object],
    chunk_count: int,
    *,
    block_offset: int,
    block_limit: int,
) -> KnowledgeParsedDocumentListItem:
    document = paginate_parsed_document(
        ParsedDocument.model_validate(_parsed_document_value(row["document"])),
        offset=block_offset,
        limit=block_limit,
    )
    return KnowledgeParsedDocumentListItem(
        chunkCount=chunk_count,
        embeddedChunkCount=int(row["embedded_chunk_count"]),
        chunkErrorMessage=(
            row["chunk_error_message"]
            if isinstance(row.get("chunk_error_message"), str)
            else None
        ),
        chunkStatus=str(row["chunk_status"]),
        createdAt=_iso_timestamp(row["created_at"]),
        fileByteSize=int(row["file_byte_size"]),
        fileHash=str(row["file_hash"]),
        fileId=str(row["file_id"]),
        fileMimeType=str(row["file_mime_type"]),
        fileName=str(row["file_name"]),
        fileStatus=str(row["file_status"]),
        parsedDocument=document,
        parsedDocumentId=str(row["parsed_document_id"]),
        updatedAt=_iso_timestamp(row["updated_at"]),
    )


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


def _feature_disabled() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "code": "knowledge_ingestion:disabled",
            "message": "Knowledge ingestion is disabled until its migration is applied.",
        },
    )


def _safe_filename(filename: str) -> str:
    candidate = SAFE_FILENAME_PATTERN.sub("_", filename).strip("._")
    candidate = candidate or "upload"
    suffix = Path(candidate).suffix
    # Preserve the parser's extension and leave space for the UUID storage prefix.
    suffix = suffix.encode("utf-8")[:20].decode("utf-8", errors="ignore")
    stem = candidate[: -len(Path(candidate).suffix)] if Path(candidate).suffix else candidate
    stem = stem.encode("utf-8")[:160 - len(suffix.encode("utf-8"))].decode(
        "utf-8", errors="ignore"
    )
    return stem + suffix


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _content_matches_extension(extension: str, content: bytes) -> bool:
    signatures = FILE_SIGNATURES.get(extension)
    if not signatures:
        return True
    return any(content.startswith(signature) for signature in signatures)


def _storage_path(settings: Settings, storage_key: str) -> Path:
    storage = get_knowledge_storage(settings)
    if not isinstance(storage, LocalKnowledgeStorage):
        raise HTTPException(
            status_code=400,
            detail="Storage paths are only available for local knowledge storage.",
        )
    try:
        return storage.path_for(storage_key)
    except StorageError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


async def _best_effort_delete(settings: Settings, storage_key: str) -> None:
    try:
        await get_knowledge_storage(settings).delete(storage_key)
    except (StorageConfigurationError, StorageError):
        return


def _extract_text(filename: str, content: bytes) -> str:
    return render_document_text(
        parse_document(filename, content),
        include_markers=True,
    )


def _chunk_text(content: str) -> list[str]:
    return [chunk for _start, _end, chunk in _chunk_text_ranges(content)]


def _chunk_text_ranges(content: str) -> list[tuple[int, int, str]]:
    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_SIZE, len(normalized))
        untrimmed = normalized[start:end]
        chunk = untrimmed.strip()
        if chunk:
            left_trim = len(untrimmed) - len(untrimmed.lstrip())
            right_trim = len(untrimmed) - len(untrimmed.rstrip())
            chunks.append((start + left_trim, end - right_trim, chunk))
        if end == len(normalized):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _chunk_parsed_document(
    document: ParsedDocument,
) -> list[tuple[str, list[dict[str, str | int]]]]:
    """Chunk rendered source text and retain the locators covered by each chunk."""
    lines: list[str] = []
    block_spans: list[tuple[int, int, dict[str, str | int]]] = []
    cursor = 0
    last_slide: int | None = None
    last_shape: int | None = None

    def append_line(line: str) -> tuple[int, int]:
        nonlocal cursor
        if lines:
            cursor += 1
        start = cursor
        lines.append(line)
        cursor += len(line)
        return start, cursor

    for block in document.blocks:
        locator = block.locator
        if "slide" in locator:
            slide_number = int(locator["slide"])
            if slide_number != last_slide:
                append_line(f"[Slide: {slide_number}]")
                last_slide = slide_number
                last_shape = None
            if "shape" in locator:
                shape_number = int(locator["shape"])
                if shape_number != last_shape:
                    append_line(f"[Shape: {shape_number}]")
                    last_shape = shape_number
        if block.text:
            start, end = append_line(block.text.replace("\r\n", "\n"))
            block_spans.append((start, end, locator))

    rendered = "\n".join(lines)
    leading_trim = len(rendered) - len(rendered.lstrip())
    normalized = rendered.strip()
    result: list[tuple[str, list[dict[str, str | int]]]] = []
    block_index = 0
    for chunk_start, chunk_end, chunk in _chunk_text_ranges(normalized):
        source_start = chunk_start + leading_trim
        source_end = chunk_end + leading_trim
        locators: list[dict[str, str | int]] = []
        while (
            block_index < len(block_spans)
            and block_spans[block_index][1] <= source_start
        ):
            block_index += 1
        current_block_index = block_index
        while current_block_index < len(block_spans):
            block_start, block_end, locator = block_spans[current_block_index]
            if block_start >= source_end:
                break
            current_block_index += 1
            if block_end <= source_start:
                continue
            normalized_locator = dict(locator)
            if normalized_locator and normalized_locator not in locators:
                locators.append(normalized_locator)
        result.append((chunk, locators))
    return result


async def _mark_knowledge_chunks_failed(
    *,
    file_id: UUID,
    workspace_id: UUID,
    parsed_document_id: UUID,
    error: Exception,
) -> None:
    retry_delay = 0.25
    attempt = 0
    while True:
        try:
            async with get_db_connection() as connection:
                async with connection.begin():
                    await connection.execute(
                        PARSED_DOCUMENT_CHUNK_STATUS_QUERY,
                        {
                            "chunk_error_message": str(error)[:1000],
                            "chunk_status": "failed",
                            "file_id": file_id,
                            "parsed_document_id": parsed_document_id,
                            "workspace_id": workspace_id,
                        },
                    )
            return
        except DatabaseServiceError as status_error:
            attempt += 1
            if attempt == 1 or attempt % 5 == 0:
                logger.warning(
                    "database unavailable while marking knowledge chunks failed; retrying",
                    extra={
                        "database_error_type": type(status_error).__name__,
                        "parsed_document_id": str(parsed_document_id),
                        "retry_attempt": attempt,
                    },
                )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 10)
        except (RuntimeError, SQLAlchemyError):
            logger.exception(
                "could not persist failed knowledge chunk status",
                extra={"parsed_document_id": str(parsed_document_id)},
            )
            return


async def process_knowledge_file(file_id: UUID, workspace_id: UUID) -> None:
    """Read one stored file and persist its ParsedDocument intermediate state."""
    settings = get_settings()
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                FILE_PROCESS_QUERY,
                {
                    "file_id": file_id,
                    "workspace_id": workspace_id,
                },
            )
            row = result.mappings().first()
    except (RuntimeError, SQLAlchemyError):
        return

    if row is None:
        return

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(
                    FILE_STATUS_QUERY,
                    {
                        "error_message": None,
                        "file_id": file_id,
                        "status": "processing",
                        "workspace_id": workspace_id,
                    },
                )

        storage = get_knowledge_storage_for_provider(
            settings,
            str(row["storage_provider"]),
        )
        content = await storage.read(str(row["storage_key"]))
        parsed_document = await asyncio.to_thread(
            parse_document,
            str(row["original_name"]),
            content,
            file_id=str(file_id),
            file_hash=str(row.get("file_hash") or ""),
            mime_type=str(
                row.get("mime_type")
                or SUPPORTED_EXTENSIONS[_extension(str(row["original_name"]))]
            ),
        )
        document = parsed_document.model_dump(by_alias=True)

        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(
                    PARSED_DOCUMENT_UPSERT_QUERY,
                    {
                        "block_count": len(parsed_document.blocks),
                        "content_type": parsed_document.content_type,
                        "document": json.dumps(document, separators=(",", ":")),
                        "file_hash": parsed_document.file_hash,
                        "file_id": file_id,
                        "knowledge_base_id": row["knowledge_base_id"],
                        "parser": parsed_document.parser,
                        "parser_version": parsed_document.parser_version,
                        "schema_version": parsed_document.schema_version,
                        "warning_count": len(parsed_document.warnings),
                        "workspace_id": workspace_id,
                    },
                )
                await connection.execute(
                    FILE_STATUS_QUERY,
                    {
                        "error_message": None,
                        "file_id": file_id,
                        "status": "ready",
                        "workspace_id": workspace_id,
                    },
                )
    except Exception as error:
        try:
            async with get_db_connection() as connection:
                async with connection.begin():
                    await connection.execute(
                        FILE_STATUS_QUERY,
                        {
                            "error_message": str(error)[:1000],
                            "file_id": file_id,
                            "status": "failed",
                            "workspace_id": workspace_id,
                        },
                    )
        except (RuntimeError, SQLAlchemyError):
            return


async def materialize_knowledge_chunks(
    file_id: UUID,
    workspace_id: UUID,
    parsed_document_id: UUID,
) -> None:
    """Turn a persisted ParsedDocument into searchable KnowledgeChunk rows."""
    try:
        async with get_db_connection() as connection:
            file_result = await connection.execute(
                FILE_PROCESS_QUERY,
                {"file_id": file_id, "workspace_id": workspace_id},
            )
            file_row = file_result.mappings().first()
    except (DatabaseServiceError, RuntimeError, SQLAlchemyError) as error:
        await _mark_knowledge_chunks_failed(
            error=error,
            file_id=file_id,
            parsed_document_id=parsed_document_id,
            workspace_id=workspace_id,
        )
        return

    if file_row is None:
        await _mark_knowledge_chunks_failed(
            error=ValueError("The source knowledge file is no longer available."),
            file_id=file_id,
            parsed_document_id=parsed_document_id,
            workspace_id=workspace_id,
        )
        return

    try:
        async with get_db_connection() as connection:
            parsed_result = await connection.execute(
                PARSED_DOCUMENT_BY_FILE_QUERY,
                {
                    "file_id": file_id,
                    "knowledge_base_id": file_row["knowledge_base_id"],
                    "workspace_id": workspace_id,
                },
            )
            parsed_row = parsed_result.mappings().first()
        if parsed_row is None:
            await _mark_knowledge_chunks_failed(
                error=ValueError("The parsed document is no longer available."),
                file_id=file_id,
                parsed_document_id=parsed_document_id,
                workspace_id=workspace_id,
            )
            return

        parsed_document_id = UUID(str(parsed_row["parsed_document_id"]))
        parsed_document = ParsedDocument.model_validate(
            _parsed_document_value(parsed_row["document"])
        )
        chunks = _chunk_parsed_document(parsed_document)
        if not chunks:
            raise ValueError("No extractable text was found in the parsed document.")

        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(CHUNKS_DELETE_QUERY, {"file_id": file_id})
                await connection.execute(
                    CHUNKS_INSERT_QUERY,
                    [
                        {
                            "chunk_index": index,
                            "content": chunk,
                            "file_id": file_id,
                            "knowledge_base_id": file_row["knowledge_base_id"],
                            "metadata": json.dumps(
                                {
                                    "fileName": file_row["original_name"],
                                    "chunkIndex": index,
                                    "fileHash": parsed_document.file_hash,
                                    "parsedDocumentId": str(parsed_document_id),
                                    "parser": parsed_document.parser,
                                    "parserVersion": parsed_document.parser_version,
                                    "locator": source_locators[0]
                                    if source_locators
                                    else None,
                                    "sourceLocators": source_locators,
                                },
                                separators=(",", ":"),
                            ),
                            "workspace_id": workspace_id,
                        }
                        for index, (chunk, source_locators) in enumerate(chunks)
                    ],
                )
                await connection.execute(
                    PARSED_DOCUMENT_CHUNK_STATUS_QUERY,
                    {
                        "chunk_error_message": None,
                        "chunk_status": "ready",
                        "file_id": file_id,
                        "parsed_document_id": parsed_document_id,
                        "workspace_id": workspace_id,
                    },
                )
    except Exception as error:
        await _mark_knowledge_chunks_failed(
            error=error,
            file_id=file_id,
            parsed_document_id=parsed_document_id,
            workspace_id=workspace_id,
        )


@router.post(
    "/{knowledge_base_id}/files/{file_id}/parse",
    response_model=None,
    status_code=status.HTTP_202_ACCEPTED,
)
async def parse_knowledge_file(
    knowledge_base_id: UUID,
    file_id: UUID,
    background_tasks: BackgroundTasks,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, KnowledgeFileSummary] | JSONResponse:
    """Explicitly queue parsing for an already uploaded knowledge file."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                FILE_BY_ID_QUERY,
                {
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            row = result.mappings().first()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not find the knowledge file to parse.")

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge file not found.",
        )

    if str(row["status"]) == "processing":
        return {"file": _file_summary(dict(row))}

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                claim = await connection.execute(
                    FILE_PARSE_CLAIM_QUERY,
                    {
                        "file_id": file_id,
                        "knowledge_base_id": knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                claimed_id = claim.scalar_one_or_none()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not start knowledge file parsing.")

    if claimed_id is not None:
        background_tasks.add_task(process_knowledge_file, file_id, workspace_id)
    row = dict(row)
    row["status"] = "processing"
    row["error_message"] = None
    return {"file": _file_summary(row)}


@router.get(
    "/{knowledge_base_id}/parsed-documents",
    response_model=KnowledgeParsedDocumentListResponse,
)
async def list_parsed_knowledge_documents(
    knowledge_base_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=100),
    block_offset: int = Query(default=0, ge=0, le=100_000),
    block_limit: int = Query(default=30, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeParsedDocumentListResponse | JSONResponse:
    """Return all persisted ParsedDocuments belonging to one knowledge base."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "read",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    page_offset = offset if isinstance(offset, int) else 0
    page_limit = limit if isinstance(limit, int) else 20
    parsed_block_offset = block_offset if isinstance(block_offset, int) else 0
    parsed_block_limit = block_limit if isinstance(block_limit, int) else 30
    query_parameters = {
        "knowledge_base_id": knowledge_base_id,
        "workspace_id": workspace_id,
    }
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                PARSED_DOCUMENT_LIST_QUERY,
                {
                    **query_parameters,
                    "limit": page_limit,
                    "offset": page_offset,
                },
            )
            rows = result.mappings().all()
            count_result = await connection.execute(
                PARSED_DOCUMENT_COUNT_QUERY,
                query_parameters,
            )
            total = int(count_result.mappings().one()["document_count"])
    except RuntimeError as error:
        return _database_error(str(error))
    except (KeyError, TypeError, ValueError, SQLAlchemyError):
        return _database_error("FastAPI could not list parsed knowledge documents.")

    try:
        items = [
            _parsed_document_list_item(
                dict(row),
                chunk_count=int(row["chunk_count"]),
                block_offset=parsed_block_offset,
                block_limit=parsed_block_limit,
            )
            for row in rows
        ]
    except (KeyError, TypeError, ValueError):
        return _database_error("FastAPI could not read parsed knowledge documents.")

    next_offset = page_offset + page_limit if page_offset + page_limit < total else None
    return KnowledgeParsedDocumentListResponse(
        items=items,
        limit=page_limit,
        nextOffset=next_offset,
        offset=page_offset,
        total=total,
    )


@router.get(
    "/{knowledge_base_id}/files/{file_id}/parsed-document",
    response_model=KnowledgeParsedDocumentResponse,
)
async def get_parsed_knowledge_document(
    knowledge_base_id: UUID,
    file_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeParsedDocumentResponse | JSONResponse:
    """Return the persisted parser output without exposing the storage object key."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "read",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    try:
        async with get_db_connection() as connection:
            parsed_result = await connection.execute(
                PARSED_DOCUMENT_BY_FILE_QUERY,
                {
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            parsed_row = parsed_result.mappings().first()
            if parsed_row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parsed document not found. Parse the file first.",
                )
            count_result = await connection.execute(
                CHUNK_COUNT_BY_FILE_QUERY,
                {
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            chunk_count = int(count_result.mappings().one()["chunk_count"])
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except (KeyError, ValueError, SQLAlchemyError):
        return _database_error("FastAPI could not load the parsed knowledge document.")

    response_row = dict(parsed_row)
    document = ParsedDocument.model_validate(_parsed_document_value(response_row["document"]))
    page_offset = offset if isinstance(offset, int) else 0
    page_limit = limit if isinstance(limit, int) else 30
    response_row["document"] = paginate_parsed_document(
        document,
        offset=page_offset,
        limit=page_limit,
    ).model_dump(by_alias=True, exclude_none=True)
    return _parsed_document_response(response_row, chunk_count)


@router.get(
    "/{knowledge_base_id}/files/{file_id}/chunks",
    response_model=KnowledgeChunkListResponse,
)
async def list_knowledge_file_chunks(
    knowledge_base_id: UUID,
    file_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeChunkListResponse | JSONResponse:
    """List file-scoped chunks for review before selecting embedding inputs."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    scope = {
        "file_id": file_id,
        "knowledge_base_id": knowledge_base_id,
        "workspace_id": workspace_id,
    }
    try:
        async with get_db_connection() as connection:
            count_result = await connection.execute(CHUNK_COUNT_BY_FILE_QUERY, scope)
            total = int(count_result.mappings().one()["chunk_count"])
            result = await connection.execute(
                CHUNK_LIST_BY_FILE_QUERY,
                {**scope, "limit": limit, "offset": offset},
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except (KeyError, TypeError, ValueError, SQLAlchemyError):
        return _database_error("FastAPI could not load knowledge file chunks.")

    items = [
        KnowledgeChunkSummary(
            chunkId=str(row["chunk_id"]),
            chunkIndex=int(row["chunk_index"]),
            content=str(row["content"]),
            embeddingModel=(
                str(row["embedding_model"])
                if row.get("embedding_model") is not None
                else None
            ),
            isEmbedded=bool(row["is_embedded"]),
        )
        for row in rows
    ]
    next_offset = offset + limit if offset + limit < total else None
    return KnowledgeChunkListResponse(
        items=items,
        limit=limit,
        nextOffset=next_offset,
        offset=offset,
        total=total,
    )


async def _embed_and_save_knowledge_chunks(
    rows: list[dict[str, object]],
    *,
    file_id: UUID,
    knowledge_base_id: UUID,
    workspace_id: UUID,
    settings: Settings,
) -> KnowledgeChunkEmbeddingResponse | JSONResponse:
    if not rows:
        return KnowledgeChunkEmbeddingResponse(
            dimensions=EMBEDDING_DIMENSIONS,
            embeddedCount=0,
            embeddingModel=settings.embedding_model,
        )

    try:
        vectors = await embed_texts([str(row["content"]) for row in rows], settings)
    except EmbeddingConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except EmbeddingProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                for row, vector in zip(rows, vectors, strict=True):
                    chunk_id = UUID(str(row["chunk_id"]))
                    update_result = await connection.execute(
                        CHUNK_EMBEDDING_UPDATE_QUERY,
                        {
                            "chunk_id": chunk_id,
                            "embedding": vector_literal(vector),
                            "embedding_model": settings.embedding_model,
                            "file_id": file_id,
                            "knowledge_base_id": knowledge_base_id,
                            "workspace_id": workspace_id,
                        },
                    )
                    if update_result.scalar_one_or_none() is None:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="A knowledge chunk changed before its embedding was saved.",
                        )
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not save knowledge chunk embeddings.")

    return KnowledgeChunkEmbeddingResponse(
        dimensions=EMBEDDING_DIMENSIONS,
        embeddedCount=len(rows),
        embeddingModel=settings.embedding_model,
    )


@router.post(
    "/{knowledge_base_id}/files/{file_id}/chunks/embeddings",
    response_model=KnowledgeChunkEmbeddingResponse,
)
async def embed_knowledge_file_chunks(
    knowledge_base_id: UUID,
    file_id: UUID,
    payload: KnowledgeChunkEmbeddingRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeChunkEmbeddingResponse | JSONResponse:
    """Embed only explicitly selected chunks belonging to this source file."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()
    if not settings.knowledge_embeddings_enabled:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "knowledge_embeddings:disabled",
                "message": "Knowledge embeddings are disabled until the provider is configured.",
            },
        )

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                CHUNKS_SELECT_FOR_EMBEDDING_QUERY,
                {
                    "chunk_ids": payload.chunk_ids,
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not load the selected knowledge chunks.")

    if len(rows) != len(payload.chunk_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more selected chunks were not found for this file.",
        )

    return await _embed_and_save_knowledge_chunks(
        rows,
        file_id=file_id,
        knowledge_base_id=knowledge_base_id,
        workspace_id=workspace_id,
        settings=settings,
    )


@router.post(
    "/{knowledge_base_id}/files/{file_id}/chunks/embeddings/all",
    response_model=KnowledgeChunkEmbeddingResponse,
)
async def embed_all_knowledge_file_chunks(
    knowledge_base_id: UUID,
    file_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeChunkEmbeddingResponse | JSONResponse:
    """Embed every unembedded or outdated-model chunk belonging to this file."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()
    if not settings.knowledge_embeddings_enabled:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "knowledge_embeddings:disabled",
                "message": "Knowledge embeddings are disabled until the provider is configured.",
            },
        )

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                CHUNKS_SELECT_FOR_ALL_EMBEDDING_QUERY,
                {
                    "embedding_model": settings.embedding_model,
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not load knowledge file chunks for embedding.")

    return await _embed_and_save_knowledge_chunks(
        rows,
        file_id=file_id,
        knowledge_base_id=knowledge_base_id,
        workspace_id=workspace_id,
        settings=settings,
    )


@router.post(
    "/{knowledge_base_id}/files/{file_id}/chunks",
    response_model=KnowledgeParsedDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def materialize_knowledge_file_chunks(
    knowledge_base_id: UUID,
    file_id: UUID,
    background_tasks: BackgroundTasks,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeParsedDocumentResponse | JSONResponse:
    """Explicitly queue ParsedDocument -> KnowledgeChunk materialization."""
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    try:
        async with get_db_connection() as connection:
            parsed_result = await connection.execute(
                PARSED_DOCUMENT_BY_FILE_QUERY,
                {
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            parsed_row = parsed_result.mappings().first()
            if parsed_row is None:
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={
                        "code": "knowledge:parsed_document_required",
                        "message": "Parse the knowledge file before generating chunks.",
                    },
            )

            if str(parsed_row["chunk_status"]) != "processing":
                # The scoped SELECT starts an implicit read transaction. Close it
                # before opening the atomic claim transaction below.
                await connection.rollback()
                async with connection.begin():
                    claim = await connection.execute(
                        PARSED_DOCUMENT_CHUNK_CLAIM_QUERY,
                        {
                            "file_id": file_id,
                            "knowledge_base_id": knowledge_base_id,
                            "parsed_document_id": parsed_row["parsed_document_id"],
                            "workspace_id": workspace_id,
                        },
                    )
                    claimed_id = claim.scalar_one_or_none()
            else:
                claimed_id = None

            count_result = await connection.execute(
                CHUNK_COUNT_BY_FILE_QUERY,
                {
                    "file_id": file_id,
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            chunk_count = int(count_result.mappings().one()["chunk_count"])
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not start knowledge chunk generation.")

    if claimed_id is not None:
        background_tasks.add_task(
            materialize_knowledge_chunks,
            file_id,
            workspace_id,
            UUID(str(parsed_row["parsed_document_id"])),
        )
        row = dict(parsed_row)
        row["chunk_status"] = "processing"
        row["chunk_error_message"] = None
    else:
        row = dict(parsed_row)
    return _parsed_document_response(row, chunk_count)


@router.get("/{knowledge_base_id}/files", response_model=KnowledgeFileListResponse)
async def list_knowledge_files(
    knowledge_base_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeFileListResponse | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "read",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                FILE_LIST_QUERY,
                {
                    "knowledge_base_id": knowledge_base_id,
                    "workspace_id": workspace_id,
                },
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not list knowledge files.")

    return KnowledgeFileListResponse(files=[_file_summary(dict(row)) for row in rows])


@router.post("/{knowledge_base_id}/files", response_model=None, status_code=202)
async def upload_knowledge_file(
    knowledge_base_id: UUID,
    file: UploadFile = File(...),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, KnowledgeFileSummary] | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    if current_user.is_development:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A persisted user is required to upload knowledge files.",
        )
    try:
        uploaded_by = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    original_name = _safe_filename(file.filename or "upload")
    extension = _extension(original_name)
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Supported file types are PDF, PPTX, CSV, XLSX, JSON, Markdown, and text.",
        )

    content = await file.read(settings.knowledge_max_file_bytes + 1)
    if len(content) > settings.knowledge_max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The knowledge file is larger than the configured limit.",
        )
    if not _content_matches_extension(extension, content):
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={
                "code": "knowledge_ingestion:invalid_content",
                "message": "The uploaded bytes do not match the declared file type.",
            },
        )

    file_id = uuid4()
    storage_key = (
        f"{workspace_id}/{knowledge_base_id}/{file_id}-{original_name}"
    )
    try:
        storage = get_knowledge_storage(settings)
        await storage.put(storage_key, content)
    except StorageConfigurationError as error:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "storage:misconfigured", "cause": str(error)},
        )
    except StorageError as error:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "storage:unavailable", "cause": str(error)},
        )

    file_hash = hashlib.sha256(content).hexdigest()
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    FILE_INSERT_QUERY,
                    {
                        "byte_size": len(content),
                        "file_hash": file_hash,
                        "file_id": file_id,
                        "knowledge_base_id": knowledge_base_id,
                        "mime_type": SUPPORTED_EXTENSIONS[extension],
                        "original_name": original_name,
                        "storage_key": storage_key,
                        "storage_provider": storage.provider,
                        "uploaded_by": uploaded_by,
                        "workspace_id": workspace_id,
                    },
                )
                inserted_id = result.scalar_one_or_none()
                if inserted_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="This file has already been uploaded to the knowledge base.",
                    )
                file_result = await connection.execute(
                    FILE_BY_ID_QUERY,
                    {
                        "file_id": inserted_id,
                        "knowledge_base_id": knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                row = file_result.mappings().one()
    except HTTPException:
        await _best_effort_delete(settings, storage_key)
        raise
    except RuntimeError as error:
        await _best_effort_delete(settings, storage_key)
        return _database_error(str(error))
    except SQLAlchemyError:
        await _best_effort_delete(settings, storage_key)
        return _database_error("FastAPI could not create the knowledge file record.")

    return {"file": _file_summary(dict(row))}


@router.delete("/{knowledge_base_id}/files/{file_id}", response_model=None)
async def delete_knowledge_file(
    knowledge_base_id: UUID,
    file_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool] | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    if not settings.knowledge_ingestion_enabled:
        return _feature_disabled()

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    FILE_DELETE_QUERY,
                    {
                        "file_id": file_id,
                        "knowledge_base_id": knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                deleted = result.mappings().first()
                if deleted is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Knowledge file not found.",
                    )
                storage_key = str(deleted["storageKey"])
                storage_provider = str(deleted["storageProvider"])
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not delete the knowledge file.")

    try:
        storage = get_knowledge_storage_for_provider(settings, storage_provider)
        await storage.delete(storage_key)
    except StorageConfigurationError as error:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "storage:misconfigured", "cause": str(error)},
        )
    except StorageError as error:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "storage:unavailable", "cause": str(error)},
        )
    return {"deleted": True}
