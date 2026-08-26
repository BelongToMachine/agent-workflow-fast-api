import json
from collections.abc import Mapping
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.permissions import (
    PERMISSION_CATALOG,
    get_effective_permissions,
    get_forbidden_permissions,
)
from app.core.workspace_access import WorkspaceAccess, require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(prefix="/admin", tags=["admin"])

WorkspaceRole = Literal["owner", "admin", "editor", "employee", "viewer"]


class PermissionOverride(BaseModel):
    effect: Literal["grant", "deny"]
    permission: str


class WorkspaceMemberView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    effective_permissions: list[str] = Field(alias="effectivePermissions")
    email: str | None
    id: str
    name: str | None = None
    overrides: list[PermissionOverride]
    role: WorkspaceRole
    status: Literal["active", "suspended"]
    user_id: str = Field(alias="userId")
    workspace_id: str = Field(alias="workspaceId")
    workspace_name: str = Field(alias="workspaceName")


class WorkspaceSummary(BaseModel):
    id: str
    name: str


class MembersResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    members: list[WorkspaceMemberView]
    workspace: WorkspaceSummary


class AccessCandidateView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str | None
    name: str | None = None
    status: Literal["active", "suspended"]
    user_id: str = Field(alias="userId")


class AccessCandidatesResponse(BaseModel):
    candidates: list[AccessCandidateView]


class UpdateMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    member_id: UUID = Field(alias="memberId")
    permissions: list[str] = Field(max_length=len(PERMISSION_CATALOG))
    role: WorkspaceRole

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            permission not in PERMISSION_CATALOG for permission in values
        ):
            raise ValueError("Unknown or duplicate permission")
        return values


class CreateMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    permissions: list[str] | None = Field(
        default=None,
        max_length=len(PERMISSION_CATALOG),
    )
    role: WorkspaceRole
    user_id: UUID = Field(alias="userId")

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return values
        if len(set(values)) != len(values) or any(
            permission not in PERMISSION_CATALOG for permission in values
        ):
            raise ValueError("Unknown or duplicate permission")
        return values


class UpdateMemberStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["active", "suspended"]


class MemberAccessError(Exception):
    """Raised when a member update violates workspace invariants."""


MEMBERS_QUERY = text(
    """
    SELECT
        member."id" AS id,
        member."role" AS role,
        member."status" AS status,
        member."userId" AS user_id,
        member."workspaceId" AS workspace_id,
        user_record."email" AS email,
        user_record."name" AS name,
        workspace."name" AS workspace_name
    FROM "WorkspaceMember" AS member
    INNER JOIN "User" AS user_record
        ON user_record."id" = member."userId"
    INNER JOIN "Workspace" AS workspace
        ON workspace."id" = member."workspaceId"
    WHERE member."workspaceId" = :workspace_id
    ORDER BY member."createdAt" ASC
    """
)

ACCESS_CANDIDATES_QUERY = text(
    """
    SELECT
        user_record."id" AS user_id,
        user_record."email" AS email,
        user_record."name" AS name,
        user_record."status" AS status
    FROM "User" AS user_record
    WHERE user_record."status" = 'active'
      AND user_record."isAnonymous" = false
      AND EXISTS (
          SELECT 1
          FROM "ExternalIdentity" AS identity
          WHERE identity."userId" = user_record."id"
      )
      AND NOT EXISTS (
          SELECT 1
          FROM "WorkspaceMember" AS member
          WHERE member."userId" = user_record."id"
            AND member."workspaceId" = :workspace_id
      )
      AND (
          :search IS NULL
          OR user_record."email" ILIKE :search
          OR user_record."name" ILIKE :search
      )
    ORDER BY COALESCE(user_record."name", user_record."email") ASC NULLS LAST,
             user_record."createdAt" ASC
    LIMIT 100
    """
)

MEMBER_OVERRIDES_QUERY = text(
    """
    SELECT
        "memberId" AS member_id,
        "effect" AS effect,
        "permission" AS permission
    FROM "WorkspaceMemberPermission"
    WHERE "memberId" IN :member_ids
    ORDER BY "updatedAt" ASC
    """
).bindparams(bindparam("member_ids", expanding=True))

TARGET_MEMBER_QUERY = text(
    """
    SELECT
        "role" AS role,
        "userId" AS user_id
    FROM "WorkspaceMember"
    WHERE "id" = :member_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

TARGET_MEMBER_STATUS_QUERY = text(
    """
    SELECT
        "role" AS role,
        "status" AS status,
        "userId" AS user_id
    FROM "WorkspaceMember"
    WHERE "id" = :member_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

TARGET_USER_QUERY = text(
    """
    SELECT
        "id" AS user_id,
        "status" AS status,
        "isAnonymous" AS is_anonymous
    FROM "User"
    WHERE "id" = :user_id
    LIMIT 1
    """
)

EXISTING_MEMBER_FOR_USER_QUERY = text(
    """
    SELECT "id" AS member_id
    FROM "WorkspaceMember"
    WHERE "userId" = :user_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

OWNER_COUNT_QUERY = text(
    """
    SELECT COUNT(*) AS owner_count
    FROM "WorkspaceMember"
    WHERE "workspaceId" = :workspace_id
      AND "role" = 'owner'
      AND "status" = 'active'
    """
)


def _build_member_views(
    member_rows: list[Mapping[str, object]],
    override_rows: list[Mapping[str, object]],
) -> list[WorkspaceMemberView]:
    overrides_by_member: dict[str, list[PermissionOverride]] = {}
    for row in override_rows:
        member_id = str(row["member_id"])
        overrides_by_member.setdefault(member_id, []).append(
            PermissionOverride(
                effect=str(row["effect"]),
                permission=str(row["permission"]),
            )
        )

    return [
        WorkspaceMemberView(
            effectivePermissions=get_effective_permissions(
                str(row["role"]),
                (
                    (override.effect, override.permission)
                    for override in overrides_by_member.get(str(row["id"]), [])
                ),
            ),
            email=row["email"] if isinstance(row["email"], str) else None,
            id=str(row["id"]),
            name=row["name"] if isinstance(row["name"], str) else None,
            overrides=overrides_by_member.get(str(row["id"]), []),
            role=str(row["role"]),
            status=str(row["status"]),
            userId=str(row["user_id"]),
            workspaceId=str(row["workspace_id"]),
            workspaceName=str(row["workspace_name"]),
        )
        for row in member_rows
    ]


def _build_access_candidate_views(
    rows: list[Mapping[str, object]],
) -> list[AccessCandidateView]:
    return [
        AccessCandidateView(
            email=row["email"] if isinstance(row["email"], str) else None,
            name=row["name"] if isinstance(row["name"], str) else None,
            status=str(row["status"]),
            userId=str(row["user_id"]),
        )
        for row in rows
    ]


def _permission_overrides(
    role: WorkspaceRole,
    permissions: list[str],
) -> list[dict[str, str]]:
    default_permissions = set(get_effective_permissions(role, (), is_guest=False))
    custom_permissions = [
        {"effect": "grant", "permission": permission}
        for permission in permissions
        if permission not in default_permissions
    ]
    denied_permissions = [
        {"effect": "deny", "permission": permission}
        for permission in default_permissions
        if permission not in permissions
    ]
    return [*custom_permissions, *denied_permissions]


async def _load_members(workspace_id: UUID) -> list[WorkspaceMemberView]:
    async with get_db_connection() as connection:
        member_result = await connection.execute(
            MEMBERS_QUERY,
            {"workspace_id": workspace_id},
        )
        member_rows = member_result.mappings().all()
        if not member_rows:
            return []

        override_result = await connection.execute(
            MEMBER_OVERRIDES_QUERY,
            {"member_ids": [row["id"] for row in member_rows]},
        )
        override_rows = override_result.mappings().all()

    return _build_member_views(member_rows, override_rows)


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


def _require_non_anonymous_development_identity(current_user: AuthenticatedUser) -> None:
    if (
        current_user.is_development
        and "permissions" not in current_user.claims
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _authorize_admin(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    permission: Literal["members.read", "members.manage"],
) -> WorkspaceAccess:
    _require_non_anonymous_development_identity(current_user)
    return await require_workspace_permission(current_user, workspace_id, permission)


@router.get("/members", response_model=MembersResponse)
async def list_members(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> MembersResponse | JSONResponse:
    await _authorize_admin(current_user, workspace_id, "members.read")

    try:
        members = await _load_members(workspace_id)
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query workspace members.")

    workspace_name = members[0].workspace_name if members else "Asianode Workspace"
    return MembersResponse(
        members=members,
        workspace={"id": str(workspace_id), "name": workspace_name},
    )


@router.get("/access-candidates", response_model=AccessCandidatesResponse)
async def list_access_candidates(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    query: str | None = Query(default=None, max_length=120),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AccessCandidatesResponse | JSONResponse:
    await _authorize_admin(current_user, workspace_id, "members.manage")

    normalized_query = query.strip() if query else None
    search = f"%{normalized_query}%" if normalized_query else None
    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                ACCESS_CANDIDATES_QUERY,
                {"workspace_id": workspace_id, "search": search},
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query access candidates.")

    return AccessCandidatesResponse(candidates=_build_access_candidate_views(rows))


async def _insert_permission_overrides(
    connection: object,
    *,
    member_id: UUID,
    role: WorkspaceRole,
    permissions: list[str],
) -> None:
    overrides = _permission_overrides(role, permissions)
    if not overrides:
        return

    await connection.execute(
        text(
            """
            INSERT INTO "WorkspaceMemberPermission"
                ("effect", "memberId", "permission", "updatedAt")
            VALUES
                (:effect, :member_id, :permission, CURRENT_TIMESTAMP)
            """
        ),
        [
            {
                "effect": override["effect"],
                "member_id": member_id,
                "permission": override["permission"],
            }
            for override in overrides
        ],
    )


async def _load_member_by_user_id(
    workspace_id: UUID,
    user_id: UUID,
) -> WorkspaceMemberView | None:
    members = await _load_members(workspace_id)
    return next((member for member in members if member.user_id == str(user_id)), None)


async def _create_member_access(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    access: WorkspaceAccess,
    body: CreateMemberRequest,
) -> WorkspaceMemberView:
    actor_user_id = UUID(current_user.user_id)
    permissions = body.permissions or get_effective_permissions(body.role, (), is_guest=False)

    if body.role == "owner" and access.role != "owner":
        raise MemberAccessError("Only the workspace owner can grant owner access.")
    if get_forbidden_permissions(body.role).intersection(permissions):
        raise MemberAccessError(
            "The employee role cannot receive knowledge permissions."
        )

    async with get_db_connection() as connection:
        async with connection.begin():
            user_result = await connection.execute(
                TARGET_USER_QUERY,
                {"user_id": body.user_id},
            )
            user = user_result.mappings().first()
            if user is None:
                raise MemberAccessError("The target user was not found.")
            if user["status"] != "active":
                raise MemberAccessError("The target user is suspended.")
            if bool(user["is_anonymous"]):
                raise MemberAccessError("Anonymous users cannot be added as members.")

            existing_result = await connection.execute(
                EXISTING_MEMBER_FOR_USER_QUERY,
                {"user_id": body.user_id, "workspace_id": workspace_id},
            )
            if existing_result.mappings().first() is not None:
                raise MemberAccessError(
                    "The target user already has a membership. Use restore instead."
                )

            member_id = uuid4()
            await connection.execute(
                text(
                    """
                    INSERT INTO "WorkspaceMember"
                        ("id", "role", "status", "userId", "workspaceId", "createdAt", "updatedAt")
                    VALUES
                        (:member_id, :role, 'active', :user_id, :workspace_id,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "member_id": member_id,
                    "role": body.role,
                    "user_id": body.user_id,
                    "workspace_id": workspace_id,
                },
            )
            await _insert_permission_overrides(
                connection,
                member_id=member_id,
                role=body.role,
                permissions=permissions,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO "AuditLog"
                        ("action", "actorUserId", "metadata", "targetUserId", "workspaceId")
                    VALUES
                        (
                            'workspace.member_added',
                            :actor_user_id,
                            CAST(:metadata AS jsonb),
                            :target_user_id,
                            :workspace_id
                        )
                    """
                ),
                {
                    "actor_user_id": actor_user_id,
                    "metadata": json.dumps(
                        {"permissions": permissions, "role": body.role},
                        separators=(",", ":"),
                    ),
                    "target_user_id": body.user_id,
                    "workspace_id": workspace_id,
                },
            )

    member = await _load_member_by_user_id(workspace_id, body.user_id)
    if member is None:
        raise RuntimeError("The created workspace member could not be loaded.")
    return member


@router.post("/members", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_member(
    request: Request,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, WorkspaceMemberView] | JSONResponse:
    access = await _authorize_admin(current_user, workspace_id, "members.manage")

    try:
        body = CreateMemberRequest.model_validate(await request.json())
    except (TypeError, ValueError, ValidationError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Invalid member access."},
        )

    try:
        member = await _create_member_access(current_user, workspace_id, access, body)
    except MemberAccessError as error:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": str(error)},
        )
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"message": "The authenticated user is not linked to a local workspace."},
        )
    except IntegrityError:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "The target user already has a membership."},
        )
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not add the workspace member.")

    return {"member": member}


async def _update_member_access(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    access: WorkspaceAccess,
    body: UpdateMemberRequest,
) -> WorkspaceMemberView | None:
    actor_user_id = UUID(current_user.user_id)

    async with get_db_connection() as connection:
        async with connection.begin():
            target_result = await connection.execute(
                TARGET_MEMBER_QUERY,
                {"member_id": body.member_id, "workspace_id": workspace_id},
            )
            target = target_result.mappings().first()
            if target is None:
                raise MemberAccessError("Workspace member not found.")

            actor_role = access.role
            target_role = str(target["role"])
            target_user_id = UUID(str(target["user_id"]))

            if target_role == "owner" and actor_role != "owner":
                raise MemberAccessError("Only the workspace owner can edit an owner.")
            if body.role == "owner" and actor_role != "owner":
                raise MemberAccessError("Only the workspace owner can grant owner access.")
            if get_forbidden_permissions(body.role).intersection(body.permissions):
                raise MemberAccessError(
                    "The employee role cannot receive knowledge permissions."
                )
            if target_user_id == actor_user_id and (
                "members.manage" not in body.permissions
                or body.role not in {"owner", "admin"}
            ):
                raise MemberAccessError("You cannot remove your own member-management access.")

            if target_role == "owner" and body.role != "owner":
                owner_result = await connection.execute(
                    OWNER_COUNT_QUERY,
                    {"workspace_id": workspace_id},
                )
                owner_count = int(owner_result.mappings().first()["owner_count"])
                if owner_count <= 1:
                    raise MemberAccessError("The workspace must keep at least one owner.")

            await connection.execute(
                text(
                    """
                    UPDATE "WorkspaceMember"
                    SET "role" = :role, "updatedAt" = CURRENT_TIMESTAMP
                    WHERE "id" = :member_id
                    """
                ),
                {"role": body.role, "member_id": body.member_id},
            )
            await connection.execute(
                text('DELETE FROM "WorkspaceMemberPermission" WHERE "memberId" = :member_id'),
                {"member_id": body.member_id},
            )

            await _insert_permission_overrides(
                connection,
                member_id=body.member_id,
                role=body.role,
                permissions=body.permissions,
            )

            await connection.execute(
                text(
                    """
                    INSERT INTO "AuditLog"
                        ("action", "actorUserId", "metadata", "targetUserId", "workspaceId")
                    VALUES
                        (
                            'workspace.member_permissions_updated',
                            :actor_user_id,
                            CAST(:metadata AS jsonb),
                            :target_user_id,
                            :workspace_id
                        )
                    """
                ),
                {
                    "actor_user_id": actor_user_id,
                    "metadata": json.dumps(
                        {"permissions": body.permissions, "role": body.role},
                        separators=(",", ":"),
                    ),
                    "target_user_id": target_user_id,
                    "workspace_id": workspace_id,
                },
            )

    updated_members = await _load_members(workspace_id)
    return next(
        (member for member in updated_members if member.user_id == str(target_user_id)),
        None,
    )


@router.patch("/members", response_model=None)
async def update_member(
    request: Request,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, WorkspaceMemberView | None] | JSONResponse:
    access = await _authorize_admin(current_user, workspace_id, "members.manage")

    try:
        body = UpdateMemberRequest.model_validate(await request.json())
    except (TypeError, ValueError, ValidationError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Invalid member permissions."},
        )

    try:
        member = await _update_member_access(current_user, workspace_id, access, body)
    except MemberAccessError as error:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": str(error)},
        )
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"message": "The authenticated user is not linked to a local workspace."},
        )
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not update workspace member access.")

    return {"member": member}


async def _update_member_status(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    access: WorkspaceAccess,
    member_id: UUID,
    body: UpdateMemberStatusRequest,
) -> WorkspaceMemberView | None:
    actor_user_id = UUID(current_user.user_id)

    async with get_db_connection() as connection:
        async with connection.begin():
            target_result = await connection.execute(
                TARGET_MEMBER_STATUS_QUERY,
                {"member_id": member_id, "workspace_id": workspace_id},
            )
            target = target_result.mappings().first()
            if target is None:
                raise MemberAccessError("Workspace member not found.")

            target_role = str(target["role"])
            target_status = str(target["status"])
            target_user_id = UUID(str(target["user_id"]))

            if target_status != body.status:
                if target_user_id == actor_user_id and body.status == "suspended":
                    raise MemberAccessError("You cannot suspend your own membership.")
                if target_role == "owner" and access.role != "owner":
                    raise MemberAccessError("Only the workspace owner can change an owner.")
                if (
                    target_status == "active"
                    and body.status == "suspended"
                    and target_role == "owner"
                ):
                    owner_result = await connection.execute(
                        OWNER_COUNT_QUERY,
                        {"workspace_id": workspace_id},
                    )
                    owner_count = int(owner_result.mappings().first()["owner_count"])
                    if owner_count <= 1:
                        raise MemberAccessError("The workspace must keep at least one owner.")

                await connection.execute(
                    text(
                        """
                        UPDATE "WorkspaceMember"
                        SET "status" = :status, "updatedAt" = CURRENT_TIMESTAMP
                        WHERE "id" = :member_id
                          AND "workspaceId" = :workspace_id
                        """
                    ),
                    {
                        "status": body.status,
                        "member_id": member_id,
                        "workspace_id": workspace_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO "AuditLog"
                            ("action", "actorUserId", "metadata", "targetUserId", "workspaceId")
                        VALUES
                            (
                                :action,
                                :actor_user_id,
                                CAST(:metadata AS jsonb),
                                :target_user_id,
                                :workspace_id
                            )
                        """
                    ),
                    {
                        "action": (
                            "workspace.member_suspended"
                            if body.status == "suspended"
                            else "workspace.member_restored"
                        ),
                        "actor_user_id": actor_user_id,
                        "metadata": json.dumps(
                            {"previousStatus": target_status, "status": body.status},
                            separators=(",", ":"),
                        ),
                        "target_user_id": target_user_id,
                        "workspace_id": workspace_id,
                    },
                )

    return await _load_member_by_user_id(workspace_id, target_user_id)


@router.patch("/members/{member_id}/status", response_model=None)
async def update_member_status(
    member_id: UUID,
    request: Request,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, WorkspaceMemberView | None] | JSONResponse:
    access = await _authorize_admin(current_user, workspace_id, "members.manage")

    try:
        body = UpdateMemberStatusRequest.model_validate(await request.json())
    except (TypeError, ValueError, ValidationError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Invalid member status."},
        )

    try:
        member = await _update_member_status(
            current_user,
            workspace_id,
            access,
            member_id,
            body,
        )
    except MemberAccessError as error:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": str(error)},
        )
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"message": "The authenticated user is not linked to a local workspace."},
        )
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not update workspace member status.")

    return {"member": member}
