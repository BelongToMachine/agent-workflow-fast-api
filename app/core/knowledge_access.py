from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser
from app.core.config import get_settings
from app.db.session import get_db_connection

AUTHORIZED_SOURCE_IDS_QUERY = text(
    """
    SELECT source."id" AS source_id
    FROM "KnowledgeSource" AS source
    WHERE source."workspaceId" = :workspace_id
      AND source."status" = 'ready'
      AND (
          :role IN ('owner', 'admin')
          OR EXISTS (
              SELECT 1
              FROM "KnowledgeBaseGrant" AS grant_record
              WHERE grant_record."workspaceId" = :workspace_id
                AND grant_record."knowledgeBaseId" = source."id"
                AND (
                    (
                        grant_record."subjectType" = 'user'
                        AND grant_record."subjectId" = :user_id
                    )
                    OR (
                        grant_record."subjectType" = 'role'
                        AND grant_record."subjectId" = :role
                    )
                )
                AND grant_record."accessLevel" IN ('read', 'manage')
          )
          OR (
              :is_restricted = false
              AND NOT EXISTS (
                  SELECT 1
                  FROM "KnowledgeBaseGrant" AS grant_record
                  WHERE grant_record."workspaceId" = :workspace_id
                    AND grant_record."knowledgeBaseId" = source."id"
              )
          )
      )
    ORDER BY source."displayName" ASC
    """
)

KNOWLEDGE_BASE_ACCESS_QUERY = text(
    """
    SELECT
        source."id" AS source_id,
        (
            :role IN ('owner', 'admin')
            OR EXISTS (
                SELECT 1
                FROM "KnowledgeBaseGrant" AS grant_record
                WHERE grant_record."workspaceId" = :workspace_id
                  AND grant_record."knowledgeBaseId" = source."id"
                  AND (
                      (
                          grant_record."subjectType" = 'user'
                          AND grant_record."subjectId" = :user_id
                      )
                      OR (
                          grant_record."subjectType" = 'role'
                          AND grant_record."subjectId" = :role
                      )
                  )
                  AND (
                      :required_access = 'read'
                      OR grant_record."accessLevel" = 'manage'
                  )
            )
            OR (
                :is_restricted = false
                AND NOT EXISTS (
                    SELECT 1
                    FROM "KnowledgeBaseGrant" AS grant_record
                    WHERE grant_record."workspaceId" = :workspace_id
                      AND grant_record."knowledgeBaseId" = source."id"
                )
            )
        ) AS permitted
    FROM "KnowledgeSource" AS source
    WHERE source."id" = :knowledge_base_id
      AND source."workspaceId" = :workspace_id
    LIMIT 1
    """
)

KNOWLEDGE_BASE_EXISTS_QUERY = text(
    """
    SELECT source."id" AS source_id
    FROM "KnowledgeSource" AS source
    WHERE source."id" = :knowledge_base_id
      AND source."workspaceId" = :workspace_id
    LIMIT 1
    """
)


async def get_authorized_source_ids(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    *,
    workspace_role: str | None = None,
    is_guest: bool | None = None,
) -> list[UUID] | None:
    """Return allowed source IDs, or None while the grant rollout is disabled."""
    if not get_settings().knowledge_grants_enabled or current_user.is_development:
        return None

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error
    role = workspace_role or current_user.role or (
        current_user.roles[0] if current_user.roles else ""
    )
    is_restricted = (
        current_user.is_guest
        or any(role in {"external", "guest"} for role in current_user.roles)
        or role in {"external", "guest"}
        or bool(is_guest)
    )
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                AUTHORIZED_SOURCE_IDS_QUERY,
                {
                    "role": role,
                    "is_restricted": is_restricted,
                    "user_id": str(user_id),
                    "workspace_id": str(workspace_id),
                },
            )
            return [row["source_id"] for row in result.mappings().all()]
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not connect to the knowledge authorization database.",
        ) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not query knowledge base grants.",
        ) from error


async def require_knowledge_base_permission(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    knowledge_base_id: UUID,
    permission: Literal["read", "manage"],
) -> object:
    """Check workspace permission plus the transitional per-knowledge-base grant."""
    from app.core.workspace_access import WorkspaceAccess, require_workspace_permission

    access: WorkspaceAccess = await require_workspace_permission(
        current_user,
        workspace_id,
        "knowledge.manage" if permission == "manage" else "knowledge.read",
    )
    if access.is_development:
        return access

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    if not get_settings().knowledge_grants_enabled:
        try:
            async with get_db_connection() as connection:
                result = await connection.execute(
                    KNOWLEDGE_BASE_EXISTS_QUERY,
                    {
                        "knowledge_base_id": knowledge_base_id,
                        "workspace_id": workspace_id,
                    },
                )
                row = result.mappings().first()
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FastAPI could not connect to the knowledge database.",
            ) from error
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FastAPI could not verify the knowledge base.",
            ) from error

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge base not found in this workspace.",
            )
        return access

    role = access.role
    is_restricted = (
        current_user.is_guest
        or any(item in {"external", "guest"} for item in current_user.roles)
        or role in {"external", "guest"}
        or access.is_guest
    )

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                KNOWLEDGE_BASE_ACCESS_QUERY,
                {
                    "is_restricted": is_restricted,
                    "knowledge_base_id": knowledge_base_id,
                    "required_access": permission,
                    "role": role,
                    "user_id": str(user_id),
                    "workspace_id": str(workspace_id),
                },
            )
            row = result.mappings().first()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not connect to the knowledge authorization database.",
        ) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not query knowledge base grants.",
        ) from error

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found in this workspace.",
        )
    if not bool(row["permitted"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have access to this knowledge base.",
        )
    return access
