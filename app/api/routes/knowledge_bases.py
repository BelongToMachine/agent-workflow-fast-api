from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.admin_knowledge_grants import _write_audit_log
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


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


KNOWLEDGE_BASE_SELECT = text(
    """
    SELECT
        "id" AS knowledge_base_id,
        "displayName" AS display_name,
        "sourceType" AS source_type,
        "status" AS status,
        "version" AS version,
        "workspaceId" AS workspace_id,
        "createdAt" AS created_at,
        "updatedAt" AS updated_at
    FROM "KnowledgeSource"
    WHERE "workspaceId" = :workspace_id
    """
)
KNOWLEDGE_BASE_INSERT = text(
    """
    INSERT INTO "KnowledgeSource"
        (
            "createdAt", "displayName", "id", "sourceType", "status",
            "updatedAt", "version", "workspaceId"
        )
    VALUES
        (CURRENT_TIMESTAMP, :display_name, :knowledge_base_id, :source_type,
         'ready', CURRENT_TIMESTAMP, 1, :workspace_id)
    RETURNING "id"
    """
)
KNOWLEDGE_BASE_UPDATE = text(
    """
    UPDATE "KnowledgeSource"
    SET "displayName" = :display_name,
        "sourceType" = :source_type,
        "updatedAt" = CURRENT_TIMESTAMP,
        "version" = "version" + 1
    WHERE "id" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
    RETURNING "id"
    """
)


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


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> KnowledgeBaseListResponse | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.read")
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                KNOWLEDGE_BASE_SELECT,
                {"workspace_id": workspace_id},
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
) -> KnowledgeBaseSummary | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.manage")
    actor_id = _require_persisted_identity(current_user)
    knowledge_base_id = uuid4()

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(
                    KNOWLEDGE_BASE_INSERT,
                    {
                        "display_name": payload.display_name,
                        "knowledge_base_id": knowledge_base_id,
                        "source_type": payload.source_type,
                        "workspace_id": workspace_id,
                    },
                )
                result = await connection.execute(
                    KNOWLEDGE_BASE_SELECT,
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
) -> KnowledgeBaseSummary | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.manage")
    actor_id = _require_persisted_identity(current_user)

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    KNOWLEDGE_BASE_UPDATE,
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
                    KNOWLEDGE_BASE_SELECT,
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
