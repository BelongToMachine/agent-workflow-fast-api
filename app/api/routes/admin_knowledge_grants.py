import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.knowledge_base_entity import render_knowledge_base_query
from app.core.workspace_access import WorkspaceAccess, require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(prefix="/admin", tags=["admin"])

SubjectType = Literal["user", "role"]
AccessLevel = Literal["read", "manage"]


class KnowledgeBaseGrantView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    grant_id: str = Field(alias="grantId")
    knowledge_base_id: str = Field(alias="knowledgeBaseId")
    knowledge_base_name: str = Field(alias="knowledgeBaseName")
    workspace_id: str = Field(alias="workspaceId")
    subject_type: SubjectType = Field(alias="subjectType")
    subject_id: str = Field(alias="subjectId")
    access_level: AccessLevel = Field(alias="accessLevel")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class KnowledgeBaseGrantsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    grants: list[KnowledgeBaseGrantView]


class UpsertKnowledgeBaseGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    knowledge_base_id: UUID = Field(alias="knowledgeBaseId")
    subject_type: SubjectType = Field(alias="subjectType")
    subject_id: str = Field(alias="subjectId", min_length=1, max_length=128)
    access_level: AccessLevel = Field(alias="accessLevel")

    @field_validator("subject_id")
    @classmethod
    def normalize_subject_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Subject ID cannot be empty.")
        return normalized


GRANTS_SELECT_TEMPLATE = """
    SELECT
        grant_record."id" AS grant_id,
        grant_record."knowledgeBaseId" AS knowledge_base_id,
        source."displayName" AS knowledge_base_name,
        grant_record."workspaceId" AS workspace_id,
        grant_record."subjectType" AS subject_type,
        grant_record."subjectId" AS subject_id,
        grant_record."accessLevel" AS access_level,
        grant_record."createdAt" AS created_at,
        grant_record."updatedAt" AS updated_at
    FROM "KnowledgeBaseGrant" AS grant_record
    INNER JOIN {knowledge_base_table} AS source
        ON source."id" = grant_record."knowledgeBaseId"
    WHERE grant_record."workspaceId" = :workspace_id
"""

GRANT_KNOWLEDGE_BASE_QUERY_TEMPLATE = """
    SELECT "id" AS knowledge_base_id
    FROM {knowledge_base_table}
    WHERE "id" = :knowledge_base_id
      AND "workspaceId" = :workspace_id
      AND "status" = 'ready'
    LIMIT 1
    """


def grants_select_query(settings: Settings | None = None) -> object:
    return text(render_knowledge_base_query(GRANTS_SELECT_TEMPLATE, settings))


def grant_by_id_query(settings: Settings | None = None) -> object:
    return text(
        render_knowledge_base_query(
            GRANTS_SELECT_TEMPLATE
            + """
      AND grant_record."id" = :grant_id
    LIMIT 1
    """,
            settings,
        )
    )


def grant_knowledge_base_query(settings: Settings | None = None) -> object:
    return text(render_knowledge_base_query(GRANT_KNOWLEDGE_BASE_QUERY_TEMPLATE, settings))


# Keep import-time constants for compatibility with existing unit tests and
# callers that inspect the transitional SQL directly.
GRANTS_SELECT = render_knowledge_base_query(GRANTS_SELECT_TEMPLATE)
GRANT_BY_ID_QUERY = text(
    GRANTS_SELECT
    + """
      AND grant_record."id" = :grant_id
    LIMIT 1
    """
)

GRANT_KNOWLEDGE_BASE_QUERY = grant_knowledge_base_query()

UPSERT_GRANT_QUERY = text(
    """
    INSERT INTO "KnowledgeBaseGrant"
        (
            "accessLevel",
            "knowledgeBaseId",
            "subjectId",
            "subjectType",
            "updatedAt",
            "workspaceId"
        )
    VALUES
        (
            :access_level,
            :knowledge_base_id,
            :subject_id,
            :subject_type,
            CURRENT_TIMESTAMP,
            :workspace_id
        )
    ON CONFLICT ("knowledgeBaseId", "subjectType", "subjectId")
    DO UPDATE SET
        "accessLevel" = EXCLUDED."accessLevel",
        "updatedAt" = CURRENT_TIMESTAMP,
        "workspaceId" = EXCLUDED."workspaceId"
    RETURNING "id"
    """
)

DELETE_GRANT_QUERY = text(
    """
    DELETE FROM "KnowledgeBaseGrant"
    WHERE "id" = :grant_id
      AND "workspaceId" = :workspace_id
    RETURNING
        "id" AS grant_id,
        "knowledgeBaseId" AS knowledge_base_id,
        "subjectType" AS subject_type,
        "subjectId" AS subject_id,
        "accessLevel" AS access_level
    """
)


def _iso_timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _build_grant_view(row: dict[str, object]) -> KnowledgeBaseGrantView:
    return KnowledgeBaseGrantView(
        grantId=str(row["grant_id"]),
        knowledgeBaseId=str(row["knowledge_base_id"]),
        knowledgeBaseName=str(row["knowledge_base_name"]),
        workspaceId=str(row["workspace_id"]),
        subjectType=str(row["subject_type"]),
        subjectId=str(row["subject_id"]),
        accessLevel=str(row["access_level"]),
        createdAt=_iso_timestamp(row["created_at"]),
        updatedAt=_iso_timestamp(row["updated_at"]),
    )


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


def _grants_disabled() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "code": "knowledge_grants:disabled",
            "message": (
                "Knowledge base grants are disabled. Apply the FastAPI migration "
                "before enabling them."
            ),
        },
    )


def _require_non_anonymous_development_identity(current_user: AuthenticatedUser) -> None:
    if current_user.is_development and not current_user.is_internal_bridge:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token or NextAuth bridge context is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _authorize_grant_admin(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
) -> WorkspaceAccess:
    _require_non_anonymous_development_identity(current_user)
    return await require_workspace_permission(current_user, workspace_id, "members.manage")


async def _load_grant(
    connection: object,
    workspace_id: UUID,
    grant_id: UUID,
    settings: Settings | None = None,
) -> KnowledgeBaseGrantView | None:
    result = await connection.execute(
        grant_by_id_query(settings),
        {"grant_id": grant_id, "workspace_id": workspace_id},
    )
    row = result.mappings().first()
    return _build_grant_view(dict(row)) if row is not None else None


async def _write_audit_log(
    connection: object,
    *,
    action: str,
    actor_user_id: str,
    workspace_id: UUID,
    metadata: dict[str, object],
) -> None:
    try:
        actor_id = UUID(actor_user_id)
    except ValueError:
        actor_id = None

    await connection.execute(
        text(
            """
            INSERT INTO "AuditLog"
                ("action", "actorUserId", "metadata", "targetUserId", "workspaceId")
            VALUES
                (:action, :actor_user_id, CAST(:metadata AS jsonb), :target_user_id, :workspace_id)
            """
        ),
        {
            "action": action,
            "actor_user_id": actor_id,
            "metadata": json.dumps(metadata, separators=(",", ":")),
            "target_user_id": None,
            "workspace_id": workspace_id,
        },
    )


@router.get(
    "/knowledge-base-grants",
    response_model=KnowledgeBaseGrantsResponse,
)
async def list_knowledge_base_grants(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    knowledge_base_id: UUID | None = Query(None, alias="knowledge_base_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeBaseGrantsResponse | JSONResponse:
    await _authorize_grant_admin(current_user, workspace_id)
    if not settings.knowledge_grants_enabled:
        return _grants_disabled()

    query = render_knowledge_base_query(GRANTS_SELECT_TEMPLATE, settings)
    params: dict[str, object] = {"workspace_id": workspace_id}
    if knowledge_base_id is not None:
        query += '      AND grant_record."knowledgeBaseId" = :knowledge_base_id\n'
        params["knowledge_base_id"] = knowledge_base_id
    query += (
        '    ORDER BY source."displayName" ASC, '
        'grant_record."subjectType" ASC, grant_record."subjectId" ASC\n'
    )

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(text(query), params)
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query knowledge base grants.")

    return KnowledgeBaseGrantsResponse(
        grants=[_build_grant_view(dict(row)) for row in rows]
    )


@router.put("/knowledge-base-grants", response_model=None)
async def upsert_knowledge_base_grant(
    request: Request,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, KnowledgeBaseGrantView | None] | JSONResponse:
    await _authorize_grant_admin(current_user, workspace_id)
    if not settings.knowledge_grants_enabled:
        return _grants_disabled()

    try:
        body = UpsertKnowledgeBaseGrantRequest.model_validate(await request.json())
    except (TypeError, ValueError, ValidationError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Invalid knowledge base grant."},
        )

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                knowledge_base_result = await connection.execute(
                    grant_knowledge_base_query(settings),
                    {
                        "knowledge_base_id": body.knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                if knowledge_base_result.mappings().first() is None:
                    return JSONResponse(
                        status_code=status.HTTP_404_NOT_FOUND,
                        content={"message": "Knowledge base not found in this workspace."},
                    )

                result = await connection.execute(
                    UPSERT_GRANT_QUERY,
                    {
                        "access_level": body.access_level,
                        "knowledge_base_id": body.knowledge_base_id,
                        "subject_id": body.subject_id,
                        "subject_type": body.subject_type,
                        "workspace_id": workspace_id,
                    },
                )
                grant_id = result.scalar_one()
                grant = await _load_grant(connection, workspace_id, grant_id, settings)
                await _write_audit_log(
                    connection,
                    action="workspace.knowledge_base_grant_updated",
                    actor_user_id=current_user.user_id,
                    workspace_id=workspace_id,
                    metadata={
                        "accessLevel": body.access_level,
                        "knowledgeBaseId": str(body.knowledge_base_id),
                        "subjectId": body.subject_id,
                        "subjectType": body.subject_type,
                    },
                )
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not update knowledge base grants.")

    return {"grant": grant}


@router.delete("/knowledge-base-grants/{grant_id}", response_model=None)
async def delete_knowledge_base_grant(
    grant_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool] | JSONResponse:
    await _authorize_grant_admin(current_user, workspace_id)
    if not settings.knowledge_grants_enabled:
        return _grants_disabled()

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    DELETE_GRANT_QUERY,
                    {"grant_id": grant_id, "workspace_id": workspace_id},
                )
                deleted = result.mappings().first()
                if deleted is None:
                    return JSONResponse(
                        status_code=status.HTTP_404_NOT_FOUND,
                        content={"message": "Knowledge base grant not found."},
                    )

                await _write_audit_log(
                    connection,
                    action="workspace.knowledge_base_grant_deleted",
                    actor_user_id=current_user.user_id,
                    workspace_id=workspace_id,
                    metadata={
                        "accessLevel": str(deleted["access_level"]),
                        "grantId": str(deleted["grant_id"]),
                        "knowledgeBaseId": str(deleted["knowledge_base_id"]),
                        "subjectId": str(deleted["subject_id"]),
                        "subjectType": str(deleted["subject_type"]),
                    },
                )
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not delete knowledge base grant.")

    return {"deleted": True}
