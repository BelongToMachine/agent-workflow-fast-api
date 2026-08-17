from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.knowledge_access import get_authorized_source_ids
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(tags=["knowledge"])


class KnowledgeSourceSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_id: str = Field(alias="sourceId")
    display_name: str = Field(alias="displayName")
    source_type: str = Field(alias="sourceType")
    status: str
    version: int
    file_hash: str | None = Field(default=None, alias="fileHash")
    storage_provider: str | None = Field(default=None, alias="storageProvider")
    workspace_id: str = Field(alias="workspaceId")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class KnowledgeSourceListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sources: list[KnowledgeSourceSummary]
    source: str = "enterprise"
    source_table: str = Field(default="KnowledgeSource", alias="sourceTable")


KNOWLEDGE_SOURCES_SELECT = """
    SELECT
        source."id" AS source_id,
        source."displayName" AS display_name,
        source."sourceType" AS source_type,
        source."status" AS status,
        source."version" AS version,
        source."fileHash" AS file_hash,
        source."storageProvider" AS storage_provider,
        source."workspaceId" AS workspace_id,
        source."createdAt" AS created_at,
        source."updatedAt" AS updated_at
    FROM "KnowledgeSource" AS source
    WHERE source."workspaceId" = :workspace_id
      AND source."status" = 'ready'
    {authorization_condition}
    ORDER BY source."displayName" ASC
"""


def _build_knowledge_sources_query(
    workspace_id: UUID,
    authorized_source_ids: list[UUID] | None,
) -> tuple[object, dict[str, object]]:
    params: dict[str, object] = {"workspace_id": str(workspace_id)}
    authorization_condition = ""
    if authorized_source_ids is not None:
        authorization_condition = 'AND source."id" IN :authorized_source_ids'
        params["authorized_source_ids"] = authorized_source_ids

    query = text(
        KNOWLEDGE_SOURCES_SELECT.format(authorization_condition=authorization_condition)
    )
    if authorized_source_ids is not None:
        query = query.bindparams(bindparam("authorized_source_ids", expanding=True))
    return query, params


def _iso_timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.get(
    "/knowledge-sources",
    response_model=KnowledgeSourceListResponse,
)
async def list_knowledge_sources(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> KnowledgeSourceListResponse | JSONResponse:
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
    query, params = _build_knowledge_sources_query(workspace_id, authorized_source_ids)

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(query, params)
            rows = result.mappings().all()
    except RuntimeError as error:
        return JSONResponse(
            status_code=503,
            content={"code": "database:unavailable", "cause": str(error)},
        )
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={
                "code": "database:unavailable",
                "cause": "FastAPI could not query knowledge sources.",
            },
        )

    return KnowledgeSourceListResponse(
        sources=[
            KnowledgeSourceSummary(
                **{
                    **row,
                    "source_id": str(row["source_id"]),
                    "workspace_id": str(row["workspace_id"]),
                    "created_at": _iso_timestamp(row["created_at"]),
                    "updated_at": _iso_timestamp(row["updated_at"]),
                }
            )
            for row in rows
        ]
    )
