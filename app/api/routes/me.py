from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.permissions import get_effective_permissions
from app.db.session import get_db_connection

router = APIRouter(tags=["identity"])


class PermissionOverride(BaseModel):
    effect: Literal["grant", "deny"]
    permission: str


class WorkspaceMembership(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    membership_id: str = Field(alias="membershipId")
    workspace_id: str = Field(alias="workspaceId")
    workspace_name: str = Field(alias="workspaceName")
    role: str
    status: str
    permissions: list[str]
    overrides: list[PermissionOverride]


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    email: str | None = None
    name: str | None = None
    is_guest: bool = Field(default=False, alias="isGuest")
    is_development: bool = Field(default=False, alias="isDevelopment")
    memberships: list[WorkspaceMembership]


USER_QUERY = text(
    """
    SELECT
        "id" AS user_id,
        "email" AS email,
        "name" AS name,
        "isAnonymous" AS is_anonymous
    FROM "User"
    WHERE "id" = :user_id
    """
)

MEMBERSHIPS_QUERY = text(
    """
    SELECT
        member."id" AS membership_id,
        member."role" AS role,
        member."status" AS status,
        member."createdAt" AS created_at,
        workspace."id" AS workspace_id,
        workspace."name" AS workspace_name
    FROM "WorkspaceMember" AS member
    INNER JOIN "Workspace" AS workspace
        ON workspace."id" = member."workspaceId"
    WHERE member."userId" = :user_id
      AND member."status" = 'active'
    ORDER BY member."createdAt" ASC
    """
)

OVERRIDES_QUERY = text(
    """
    SELECT
        "memberId" AS membership_id,
        "effect" AS effect,
        "permission" AS permission
    FROM "WorkspaceMemberPermission"
    WHERE "memberId" IN :membership_ids
    ORDER BY "updatedAt" ASC
    """
).bindparams(bindparam("membership_ids", expanding=True))


def _uuid_value(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error


def _build_memberships(
    membership_rows: list[dict[str, object]],
    override_rows: list[dict[str, object]],
    *,
    is_guest: bool,
) -> list[WorkspaceMembership]:
    overrides_by_membership: dict[UUID, list[PermissionOverride]] = {}
    for row in override_rows:
        membership_id = row["membership_id"]
        overrides_by_membership.setdefault(membership_id, []).append(
            PermissionOverride(effect=row["effect"], permission=row["permission"])
        )

    memberships = []
    for row in membership_rows:
        membership_id = row["membership_id"]
        overrides = overrides_by_membership.get(membership_id, [])
        permissions = get_effective_permissions(
            str(row["role"]),
            ((override.effect, override.permission) for override in overrides),
            is_guest=is_guest,
        )
        memberships.append(
            WorkspaceMembership(
                membershipId=str(membership_id),
                workspaceId=str(row["workspace_id"]),
                workspaceName=str(row["workspace_name"]),
                role=str(row["role"]),
                status=str(row["status"]),
                permissions=permissions,
                overrides=overrides,
            )
        )
    return memberships


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> CurrentUserResponse:
    if current_user.is_development:
        return CurrentUserResponse(
            userId=current_user.user_id,
            email=current_user.email,
            name=None,
            isGuest=False,
            isDevelopment=True,
            memberships=[],
        )

    user_id = _uuid_value(current_user.user_id)
    try:
        async with get_db_connection() as connection:
            user_result = await connection.execute(USER_QUERY, {"user_id": user_id})
            user_row = user_result.mappings().first()
            if user_row is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The authenticated user is not registered in this workspace.",
                )

            membership_result = await connection.execute(MEMBERSHIPS_QUERY, {"user_id": user_id})
            membership_rows = membership_result.mappings().all()
            override_rows = []
            if membership_rows:
                override_result = await connection.execute(
                    OVERRIDES_QUERY,
                    {"membership_ids": [row["membership_id"] for row in membership_rows]},
                )
                override_rows = override_result.mappings().all()
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
            detail="FastAPI could not query workspace membership.",
        ) from error

    is_guest = bool(user_row["is_anonymous"]) or "guest" in current_user.roles
    return CurrentUserResponse(
        userId=str(user_row["user_id"]),
        email=user_row["email"],
        name=user_row["name"],
        isGuest=is_guest,
        isDevelopment=False,
        memberships=_build_memberships(
            membership_rows,
            override_rows,
            is_guest=is_guest,
        ),
    )
