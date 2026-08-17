import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.admin_knowledge_grants import _write_audit_log
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.knowledge_access import (
    get_authorized_source_ids,
    require_knowledge_base_permission,
)
from app.core.knowledge_base_entity import render_knowledge_base_query
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection
from app.services.storage import (
    StorageConfigurationError,
    StorageError,
    get_knowledge_storage_for_provider,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])
logger = logging.getLogger(__name__)


class KnowledgeBaseSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_base_id: str = Field(alias="knowledgeBaseId")
    display_name: str = Field(alias="displayName")
    source_type: str = Field(alias="sourceType")
    status: str
    version: int
    workspace_id: str = Field(alias="workspaceId")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class KnowledgeBaseListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_bases: list[KnowledgeBaseSummary] = Field(alias="knowledgeBases")


class KnowledgeBaseWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    source_type: str = Field(default="manual", alias="sourceType", min_length=1, max_length=32)

    @field_validator("display_name", "source_type")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("The value cannot be empty.")
        return normalized


KNOWLEDGE_BASE_SELECT_TEMPLATE = """
    SELECT
        "id" AS knowledge_base_id,
        "displayName" AS display_name,
        "sourceType" AS source_type,
        "status" AS status,
        "version" AS version,
        "workspaceId" AS workspace_id,
        "createdAt" AS created_at,
        "updatedAt" AS updated_at
    FROM {knowledge_base_table}
    WHERE "workspaceId" = :workspace_id
    {authorization_condition}
    """
KNOWLEDGE_BASE_INSERT_TEMPLATE = """
    INSERT INTO {knowledge_base_table}
        (
            "createdAt", "displayName", "id", "sourceType", "status",
            "updatedAt", "version", "workspaceId"
        )
    VALUES
        (CURRENT_TIMESTAMP, :display_name, :knowledge_base_id, :source_type,
         'ready', CURRENT_TIMESTAMP, 1, :workspace_id)
    RETURNING "id"
    """
KNOWLEDGE_BASE_UPDATE_TEMPLATE = """
    UPDATE {knowledge_base_table}
    SET "displayName" = :display_name,
        "sourceType" = :source_type,
        "updatedAt" = CURRENT_TIMESTAMP,
        "version" = "version" + 1
    WHERE "id" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    RETURNING "id"
    """

KNOWLEDGE_BASE_FILE_KEYS_QUERY = text(
    """
    SELECT "storageKey" AS storage_key, "storageProvider" AS storage_provider
    FROM "KnowledgeFile"
    WHERE "knowledgeBaseId" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    """
)
KNOWLEDGE_BASE_DELETE_TEMPLATE = """
    DELETE FROM {knowledge_base_table}
    WHERE "id" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    RETURNING "id"
    """


def knowledge_base_select_query(
    settings: Settings | None = None,
    authorized_source_ids: list[UUID] | None = None,
) -> object:
    authorization_condition = ""
    if authorized_source_ids is not None:
        authorization_condition = 'AND "id" IN :authorized_source_ids'
    query = text(
        render_knowledge_base_query(
            KNOWLEDGE_BASE_SELECT_TEMPLATE.replace(
                "{authorization_condition}", authorization_condition
            ),
            settings,
        )
    )
    if authorized_source_ids is not None:
        query = query.bindparams(bindparam("authorized_source_ids", expanding=True))
    return query


def knowledge_base_insert_query(settings: Settings | None = None) -> object:
    return text(render_knowledge_base_query(KNOWLEDGE_BASE_INSERT_TEMPLATE, settings))


def knowledge_base_update_query(settings: Settings | None = None) -> object:
    return text(render_knowledge_base_query(KNOWLEDGE_BASE_UPDATE_TEMPLATE, settings))


def knowledge_base_delete_query(settings: Settings | None = None) -> object:
    return text(render_knowledge_base_query(KNOWLEDGE_BASE_DELETE_TEMPLATE, settings))


# Keep import-time query constants for callers and tests that still exercise the
# transitional KnowledgeSource path directly.
KNOWLEDGE_BASE_SELECT = knowledge_base_select_query()
KNOWLEDGE_BASE_INSERT = knowledge_base_insert_query()
KNOWLEDGE_BASE_UPDATE = knowledge_base_update_query()
KNOWLEDGE_BASE_DELETE = knowledge_base_delete_query()


def _iso_timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _summary(row: dict[str, object]) -> KnowledgeBaseSummary:
    return KnowledgeBaseSummary(
        knowledgeBaseId=str(row["knowledge_base_id"]),
        displayName=str(row["display_name"]),
        sourceType=str(row["source_type"]),
        status=str(row["status"]),
        version=int(row["version"]),
        workspaceId=str(row["workspace_id"]),
        createdAt=_iso_timestamp(row["created_at"]),
        updatedAt=_iso_timestamp(row["updated_at"]),
    )


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


def _require_persisted_identity(current_user: AuthenticatedUser) -> UUID:
    if current_user.is_development:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token or NextAuth bridge context is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error


async def _cleanup_knowledge_base_files(
    settings: Settings,
    file_rows: list[dict[str, object]],
) -> int:
    failed_count = 0
    for row in file_rows:
        try:
            storage = get_knowledge_storage_for_provider(
                settings,
                str(row["storage_provider"]),
            )
            await storage.delete(str(row["storage_key"]))
        except (StorageConfigurationError, StorageError):
            failed_count += 1
            logger.exception(
                "Knowledge-base storage cleanup failed for provider=%s",
                row["storage_provider"],
            )
    return failed_count


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeBaseListResponse | JSONResponse:
    workspace_access = await require_workspace_permission(
        current_user,
        workspace_id,
        "knowledge.read",
    )
    authorized_source_ids = await get_authorized_source_ids(
        current_user,
        workspace_id,
        is_guest=workspace_access.is_guest,
        workspace_role=workspace_access.role,
    )
    params: dict[str, object] = {"workspace_id": workspace_id}
    if authorized_source_ids is not None:
        params["authorized_source_ids"] = authorized_source_ids
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                knowledge_base_select_query(settings, authorized_source_ids),
                params,
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not list knowledge bases.")

    return KnowledgeBaseListResponse(
        knowledgeBases=[_summary(dict(row)) for row in rows]
    )


@router.post("", response_model=KnowledgeBaseSummary, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseWriteRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeBaseSummary | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.manage")
    actor_id = _require_persisted_identity(current_user)
    knowledge_base_id = uuid4()

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(
                    knowledge_base_insert_query(settings),
                    {
                        "display_name": payload.display_name,
                        "knowledge_base_id": knowledge_base_id,
                        "source_type": payload.source_type,
                        "workspace_id": workspace_id,
                    },
                )
                result = await connection.execute(
                    knowledge_base_select_query(settings),
                    {"workspace_id": workspace_id},
                )
                row = next(
                    item
                    for item in result.mappings().all()
                    if item["knowledge_base_id"] == knowledge_base_id
                )
                await _write_audit_log(
                    connection,
                    action="workspace.knowledge_base_created",
                    actor_user_id=str(actor_id),
                    workspace_id=workspace_id,
                    metadata={
                        "knowledgeBaseId": str(knowledge_base_id),
                        "displayName": payload.display_name,
                        "sourceType": payload.source_type,
                    },
                )
    except StopIteration:
        return _database_error("FastAPI could not load the created knowledge base.")
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not create the knowledge base.")

    return _summary(dict(row))


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseSummary)
async def update_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeBaseWriteRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeBaseSummary | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.manage")
    actor_id = _require_persisted_identity(current_user)

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    knowledge_base_update_query(settings),
                    {
                        "display_name": payload.display_name,
                        "knowledge_base_id": knowledge_base_id,
                        "source_type": payload.source_type,
                        "workspace_id": workspace_id,
                    },
                )
                if result.scalar_one_or_none() is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Knowledge base not found in this workspace.",
                    )
                result = await connection.execute(
                    knowledge_base_select_query(settings),
                    {"workspace_id": workspace_id},
                )
                row = next(
                    item
                    for item in result.mappings().all()
                    if item["knowledge_base_id"] == knowledge_base_id
                )
                await _write_audit_log(
                    connection,
                    action="workspace.knowledge_base_updated",
                    actor_user_id=str(actor_id),
                    workspace_id=workspace_id,
                    metadata={
                        "knowledgeBaseId": str(knowledge_base_id),
                        "displayName": payload.display_name,
                        "sourceType": payload.source_type,
                    },
                )
    except HTTPException:
        raise
    except StopIteration:
        return _database_error("FastAPI could not load the updated knowledge base.")
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not update the knowledge base.")

    return _summary(dict(row))


@router.delete("/{knowledge_base_id}", response_model=None)
async def delete_knowledge_base(
    knowledge_base_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, object] | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "manage",
    )
    actor_id = _require_persisted_identity(current_user)
    file_rows: list[dict[str, object]] = []

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                if settings.knowledge_ingestion_enabled:
                    file_result = await connection.execute(
                        KNOWLEDGE_BASE_FILE_KEYS_QUERY,
                        {
                            "knowledge_base_id": knowledge_base_id,
                            "workspace_id": workspace_id,
                        },
                    )
                    file_rows = [dict(row) for row in file_result.mappings().all()]

                result = await connection.execute(
                    knowledge_base_delete_query(settings),
                    {
                        "knowledge_base_id": knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                deleted = result.mappings().first()
                if deleted is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Knowledge base not found in this workspace.",
                    )
                await _write_audit_log(
                    connection,
                    action="workspace.knowledge_base_deleted",
                    actor_user_id=str(actor_id),
                    workspace_id=workspace_id,
                    metadata={
                        "knowledgeBaseId": str(knowledge_base_id),
                        "fileCount": len(file_rows),
                    },
                )
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not delete the knowledge base.")

    failed_storage_files = await _cleanup_knowledge_base_files(settings, file_rows)
    if failed_storage_files:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "deleted": True,
                "storageCleanup": "pending",
                "failedFileCount": failed_storage_files,
            },
        )
    return {
        "deleted": True,
        "storageCleanup": "completed" if file_rows else "not_required",
    }
