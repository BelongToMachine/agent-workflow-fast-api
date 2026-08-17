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
          NOT EXISTS (
              SELECT 1
              FROM "KnowledgeBaseGrant" AS grant_record
              WHERE grant_record."workspaceId" = :workspace_id
                AND grant_record."knowledgeBaseId" = source."id"
          )
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
      )
    ORDER BY source."displayName" ASC
    """
)


async def get_authorized_source_ids(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
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

    role = current_user.role or (current_user.roles[0] if current_user.roles else "")
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                AUTHORIZED_SOURCE_IDS_QUERY,
                {
                    "role": role,
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
