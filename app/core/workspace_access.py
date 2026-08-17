from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser
from app.core.permissions import get_effective_permissions
from app.db.session import get_db_connection


class WorkspaceAccess:
    def __init__(
        self,
        *,
        user_id: str,
        workspace_id: UUID,
        role: str,
        permissions: list[str],
        is_guest: bool,
        is_development: bool,
    ) -> None:
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.role = role
        self.permissions = permissions
        self.is_guest = is_guest
        self.is_development = is_development


MEMBERSHIP_QUERY = text(
    """
    SELECT
        member."id" AS membership_id,
        member."role" AS role,
        user_record."isAnonymous" AS is_anonymous
    FROM "WorkspaceMember" AS member
    INNER JOIN "User" AS user_record
        ON user_record."id" = member."userId"
    WHERE member."userId" = :user_id
      AND member."workspaceId" = :workspace_id
      AND member."status" = 'active'
    LIMIT 1
    """
)

OVERRIDES_QUERY = text(
    """
    SELECT "effect" AS effect, "permission" AS permission
    FROM "WorkspaceMemberPermission"
    WHERE "memberId" = :membership_id
    ORDER BY "updatedAt" ASC
    """
)


async def require_workspace_permission(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    permission: str,
) -> WorkspaceAccess:
    if current_user.is_development:
        return WorkspaceAccess(
            user_id=current_user.user_id,
            workspace_id=workspace_id,
            role="owner",
            permissions=get_effective_permissions("owner", []),
            is_guest=False,
            is_development=True,
        )

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    try:
        async with get_db_connection() as connection:
            membership_result = await connection.execute(
                MEMBERSHIP_QUERY,
                {"user_id": user_id, "workspace_id": workspace_id},
            )
            membership = membership_result.mappings().first()
            if membership is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The user has no active membership in this workspace.",
                )

            override_result = await connection.execute(
                OVERRIDES_QUERY,
                {"membership_id": membership["membership_id"]},
            )
            overrides = [
                (row["effect"], row["permission"]) for row in override_result.mappings().all()
            ]
    except HTTPException:
        raise
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not connect to the workspace database.",
        ) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not query workspace permissions.",
        ) from error

    is_guest = (
        bool(membership["is_anonymous"])
        or current_user.is_guest
        or "guest" in current_user.roles
    )
    permissions = get_effective_permissions(str(membership["role"]), overrides, is_guest=is_guest)
    if permission not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have permission to access this workspace data.",
        )

    return WorkspaceAccess(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        role=str(membership["role"]),
        permissions=permissions,
        is_guest=is_guest,
        is_development=False,
    )
