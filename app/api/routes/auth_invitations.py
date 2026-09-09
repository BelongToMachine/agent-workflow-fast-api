"""Administrator invitations and first-password activation."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.routes.auth_local import (
    LocalSessionResponse,
    _ensure_local_auth_mode,
    _metadata_hash,
    _require_csrf,
    _set_session_cookie,
    normalize_email,
)
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.one_time_tokens import hash_one_time_token, new_one_time_token
from app.core.passwords import PasswordPolicyError, hash_password, normalize_password
from app.core.workspace_access import WorkspaceAccess, require_workspace_permission
from app.db.auth_sessions import AuthSessionRepository
from app.db.session import get_db_connection

WorkspaceRole = Literal["owner", "admin", "editor", "employee", "viewer"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email: str = Field(min_length=3, max_length=320)
    workspace_id: UUID = Field(alias="workspaceId")
    role: WorkspaceRole = "employee"
    expires_in_seconds: int | None = Field(
        default=None,
        alias="expiresInSeconds",
        ge=15 * 60,
        le=30 * 24 * 60 * 60,
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("A valid email address is required.")
        return normalized


class InvitationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invitation_id: str = Field(alias="invitationId")
    email: str
    workspace_id: str = Field(alias="workspaceId")
    role: WorkspaceRole
    expires_at: datetime = Field(alias="expiresAt")
    activation_url: str = Field(alias="activationUrl")


InvitationStatus = Literal["pending", "expired", "revoked", "accepted"]


class InvitationListItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invitation_id: str = Field(alias="invitationId")
    email: str
    workspace_id: str = Field(alias="workspaceId")
    role: WorkspaceRole
    status: InvitationStatus
    expires_at: datetime = Field(alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")


class InvitationsResponse(BaseModel):
    invitations: list[InvitationListItem]


class InvitationRevokeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invitation_id: str = Field(alias="invitationId")
    revoked: bool


class ActivateInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=1024)
    name: str | None = Field(default=None, max_length=200)


INVITATION_WORKSPACE_QUERY = text(
    """
    SELECT "id"
    FROM "Workspace"
    WHERE "id" = :workspace_id
    LIMIT 1
    """
)

EXISTING_LOCAL_ACCOUNT_QUERY = text(
    """
    SELECT user_record."id"
    FROM "User" AS user_record
    INNER JOIN "PasswordCredential" AS credential
        ON credential."userId" = user_record."id"
    WHERE lower(btrim(user_record."email")) = :normalized_email
      AND user_record."status" = 'active'
    LIMIT 1
    """
)

REVOKE_PENDING_INVITATIONS_QUERY = text(
    """
    UPDATE "AuthOneTimeToken"
    SET "revokedAt" = CURRENT_TIMESTAMP
    WHERE "normalizedEmail" = :normalized_email
      AND "workspaceId" = :workspace_id
      AND "purpose" = 'invitation'
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
    """
)

INSERT_INVITATION_QUERY = text(
    """
    INSERT INTO "AuthOneTimeToken" (
        "id", "normalizedEmail", "purpose", "tokenHash", "workspaceId",
        "workspaceRole", "expiresAt", "createdBy", "createdAt"
    )
    VALUES (
        :invitation_id, :normalized_email, 'invitation', :token_hash, :workspace_id,
        :workspace_role, :expires_at, :created_by, CURRENT_TIMESTAMP
    )
    """
)

INVITATION_BY_ID_QUERY = text(
    """
    SELECT
        "id" AS invitation_id,
        "normalizedEmail" AS normalized_email,
        "workspaceId" AS workspace_id,
        "workspaceRole" AS workspace_role,
        "expiresAt" AS expires_at,
        "usedAt" AS used_at,
        "revokedAt" AS revoked_at
    FROM "AuthOneTimeToken"
    WHERE "id" = :invitation_id
      AND "purpose" = 'invitation'
      AND "workspaceId" = :workspace_id
    FOR UPDATE
    """
)

LIST_INVITATIONS_QUERY = text(
    """
    SELECT
        "id" AS invitation_id,
        "normalizedEmail" AS email,
        "workspaceId" AS workspace_id,
        "workspaceRole" AS role,
        "expiresAt" AS expires_at,
        "createdAt" AS created_at,
        CASE
            WHEN "usedAt" IS NOT NULL THEN 'accepted'
            WHEN "revokedAt" IS NOT NULL THEN 'revoked'
            WHEN "expiresAt" <= CURRENT_TIMESTAMP THEN 'expired'
            ELSE 'pending'
        END AS status
    FROM "AuthOneTimeToken"
    WHERE "workspaceId" = :workspace_id
      AND "purpose" = 'invitation'
    ORDER BY "createdAt" DESC
    LIMIT 100
    """
)

REVOKE_INVITATION_QUERY = text(
    """
    UPDATE "AuthOneTimeToken"
    SET "revokedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :invitation_id
      AND "purpose" = 'invitation'
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
    """
)

ACTIVATION_TOKEN_QUERY = text(
    """
    SELECT
        "id" AS invitation_id,
        "normalizedEmail" AS normalized_email,
        "workspaceId" AS workspace_id,
        "workspaceRole" AS workspace_role,
        "expiresAt" AS expires_at
    FROM "AuthOneTimeToken"
    WHERE "tokenHash" = :token_hash
      AND "purpose" = 'invitation'
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
      AND "expiresAt" > CURRENT_TIMESTAMP
    FOR UPDATE
    """
)

INSERT_USER_QUERY = text(
    """
    INSERT INTO "User" (
        "id", "email", "name", "emailVerified", "isAnonymous", "status",
        "createdAt", "updatedAt"
    )
    VALUES (
        :user_id, :email, :name, true, false, 'active',
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    """
)

INSERT_PASSWORD_CREDENTIAL_QUERY = text(
    """
    INSERT INTO "PasswordCredential" (
        "userId", "passwordHash", "passwordVersion", "passwordChangedAt",
        "createdAt", "updatedAt"
    )
    VALUES (
        :user_id, :password_hash, 1, CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    """
)

INSERT_WORKSPACE_MEMBER_QUERY = text(
    """
    INSERT INTO "WorkspaceMember" (
        "id", "role", "status", "userId", "workspaceId", "createdAt", "updatedAt"
    )
    VALUES (
        :member_id, :workspace_role, 'active', :user_id, :workspace_id,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    """
)

MARK_INVITATION_USED_QUERY = text(
    """
    UPDATE "AuthOneTimeToken"
    SET "usedAt" = CURRENT_TIMESTAMP,
        "userId" = :user_id
    WHERE "id" = :invitation_id
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
    """
)

INSERT_AUTH_AUDIT_QUERY = text(
    """
    INSERT INTO "AuthAuditLog" (
        "eventType", "userId", "sessionId", "ipHash", "userAgentHash", "metadata"
    )
    VALUES (
        :event_type, :user_id, :session_id, :ip_hash, :user_agent_hash,
        CAST(:metadata AS jsonb)
    )
    """
)

ADVISORY_EMAIL_LOCK_QUERY = text("SELECT pg_advisory_xact_lock(hashtext(:normalized_email))")

router = APIRouter(
    prefix="/admin/auth",
    tags=["local-auth-admin"],
    dependencies=[Depends(_ensure_local_auth_mode)],
)

auth_router = APIRouter(
    prefix="/auth",
    tags=["local-auth"],
    dependencies=[Depends(_ensure_local_auth_mode)],
)


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _actor_uuid(current_user: AuthenticatedUser) -> UUID | None:
    if current_user.is_development:
        return None
    try:
        return UUID(current_user.user_id)
    except ValueError:
        return None


def _workspace_role(value: object) -> WorkspaceRole:
    if value not in {"owner", "admin", "editor", "employee", "viewer"}:
        raise _auth_error(400, "auth:invitation_invalid", "The invitation is invalid.")
    return value  # type: ignore[return-value]


def _activation_url(token: str, settings: Settings) -> str:
    # The raw one-time token is only returned in the immediate create or
    # regenerate response and is never stored.
    return f"{settings.auth_frontend_url.rstrip('/')}/activate?token={quote(token, safe='')}"


def _database_unavailable(error: Exception) -> HTTPException:
    return _auth_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "auth:storage_unavailable",
        "Authentication storage is unavailable.",
    )


async def _authorize_invitation_admin(
    current_user: AuthenticatedUser,
    workspace_id: UUID,
) -> WorkspaceAccess:
    try:
        return await require_workspace_permission(current_user, workspace_id, "members.manage")
    except HTTPException:
        raise
    except (RuntimeError, SQLAlchemyError) as error:
        raise _database_unavailable(error) from error


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: CreateInvitationRequest,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvitationResponse:
    """Create one pending invitation for a workspace member.

    The response includes a one-time activation URL. No email delivery is
    performed by this endpoint; the administrator shares the link privately.
    """
    access = await _authorize_invitation_admin(current_user, payload.workspace_id)
    if payload.role == "owner" and access.role != "owner":
        raise _auth_error(
            status.HTTP_403_FORBIDDEN,
            "workspace:owner_required",
            "Only the workspace owner can invite another owner.",
        )

    token = new_one_time_token()
    invitation_id = uuid4()
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=payload.expires_in_seconds or settings.auth_invitation_ttl_seconds
    )
    created_by = _actor_uuid(current_user)

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                await connection.execute(
                    ADVISORY_EMAIL_LOCK_QUERY,
                    {"normalized_email": payload.email},
                )
                workspace_result = await connection.execute(
                    INVITATION_WORKSPACE_QUERY,
                    {"workspace_id": payload.workspace_id},
                )
                if workspace_result.mappings().first() is None:
                    raise _auth_error(
                        status.HTTP_404_NOT_FOUND,
                        "workspace:not_found",
                        "The workspace was not found.",
                    )

                account_result = await connection.execute(
                    EXISTING_LOCAL_ACCOUNT_QUERY,
                    {"normalized_email": payload.email},
                )
                if account_result.mappings().first() is not None:
                    raise _auth_error(
                        status.HTTP_409_CONFLICT,
                        "auth:account_exists",
                        "A local account already exists for this email.",
                    )

                await connection.execute(
                    REVOKE_PENDING_INVITATIONS_QUERY,
                    {
                        "normalized_email": payload.email,
                        "workspace_id": payload.workspace_id,
                    },
                )
                await connection.execute(
                    INSERT_INVITATION_QUERY,
                    {
                        "invitation_id": invitation_id,
                        "normalized_email": payload.email,
                        "token_hash": token.token_hash,
                        "workspace_id": payload.workspace_id,
                        "workspace_role": payload.role,
                        "expires_at": expires_at,
                        "created_by": created_by,
                    },
                )
                await connection.execute(
                    INSERT_AUTH_AUDIT_QUERY,
                    {
                        "event_type": "auth.invitation_created",
                        "user_id": created_by,
                        "session_id": None,
                        "ip_hash": _metadata_hash(
                            request.client.host if request.client else None,
                            settings,
                        ),
                        "user_agent_hash": _metadata_hash(
                            request.headers.get("user-agent"),
                            settings,
                        ),
                        "metadata": '{"purpose":"invitation"}',
                    },
                )
    except HTTPException:
        raise
    except IntegrityError as error:
        raise _auth_error(
            status.HTTP_409_CONFLICT,
            "auth:invitation_conflict",
            "The invitation could not be created because the account state changed.",
        ) from error
    except (RuntimeError, SQLAlchemyError) as error:
        raise _database_unavailable(error) from error

    return InvitationResponse(
        invitationId=str(invitation_id),
        email=payload.email,
        workspaceId=str(payload.workspace_id),
        role=payload.role,
        expiresAt=expires_at,
        activationUrl=_activation_url(token.token, settings),
    )


@router.get("/invitations", response_model=InvitationsResponse)
async def list_invitations(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    workspace_id: UUID = Query(alias="workspace_id"),
) -> InvitationsResponse:
    """List recent invitations without exposing bearer activation tokens."""
    await _authorize_invitation_admin(current_user, workspace_id)

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                LIST_INVITATIONS_QUERY,
                {"workspace_id": workspace_id},
            )
            rows = result.mappings().all()
    except (RuntimeError, SQLAlchemyError) as error:
        raise _database_unavailable(error) from error

    return InvitationsResponse(
        invitations=[
            InvitationListItem(
                invitationId=str(row["invitation_id"]),
                email=str(row["email"]),
                workspaceId=str(row["workspace_id"]),
                role=_workspace_role(row["role"]),
                status=row["status"],
                expiresAt=row["expires_at"],
                createdAt=row["created_at"],
            )
            for row in rows
        ]
    )


@router.post(
    "/invitations/{invitation_id}/regenerate",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_invitation(
    invitation_id: UUID,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: UUID = Query(alias="workspace_id"),
) -> InvitationResponse:
    """Revoke an unused invitation and issue a fresh one-time link."""
    await _authorize_invitation_admin(current_user, workspace_id)
    actor_id = _actor_uuid(current_user)
    token = new_one_time_token()
    new_invitation_id = uuid4()
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=settings.auth_invitation_ttl_seconds
    )

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    INVITATION_BY_ID_QUERY,
                    {
                        "invitation_id": invitation_id,
                        "workspace_id": workspace_id,
                    },
                )
                invitation = result.mappings().first()
                if invitation is None:
                    raise _auth_error(
                        status.HTTP_404_NOT_FOUND,
                        "auth:invitation_not_found",
                        "The invitation was not found.",
                    )
                if invitation["used_at"] is not None:
                    raise _auth_error(
                        status.HTTP_409_CONFLICT,
                        "auth:invitation_not_pending",
                        "The invitation has already been used.",
                    )

                normalized_email = str(invitation["normalized_email"])
                await connection.execute(
                    ADVISORY_EMAIL_LOCK_QUERY,
                    {"normalized_email": normalized_email},
                )
                account_result = await connection.execute(
                    EXISTING_LOCAL_ACCOUNT_QUERY,
                    {"normalized_email": normalized_email},
                )
                if account_result.mappings().first() is not None:
                    raise _auth_error(
                        status.HTTP_409_CONFLICT,
                        "auth:account_exists",
                        "A local account already exists for this email.",
                    )

                await connection.execute(
                    REVOKE_PENDING_INVITATIONS_QUERY,
                    {
                        "normalized_email": normalized_email,
                        "workspace_id": workspace_id,
                    },
                )
                await connection.execute(
                    INSERT_INVITATION_QUERY,
                    {
                        "invitation_id": new_invitation_id,
                        "normalized_email": normalized_email,
                        "token_hash": token.token_hash,
                        "workspace_id": workspace_id,
                        "workspace_role": _workspace_role(invitation["workspace_role"]),
                        "expires_at": expires_at,
                        "created_by": actor_id,
                    },
                )
                await connection.execute(
                    INSERT_AUTH_AUDIT_QUERY,
                    {
                        "event_type": "auth.invitation_regenerated",
                        "user_id": actor_id,
                        "session_id": None,
                        "ip_hash": _metadata_hash(
                            request.client.host if request.client else None,
                            settings,
                        ),
                        "user_agent_hash": _metadata_hash(
                            request.headers.get("user-agent"),
                            settings,
                        ),
                        "metadata": '{"purpose":"invitation"}',
                    },
                )
    except HTTPException:
        raise
    except IntegrityError as error:
        raise _auth_error(
            status.HTTP_409_CONFLICT,
            "auth:invitation_conflict",
            "The invitation could not be regenerated because the account state changed.",
        ) from error
    except (RuntimeError, SQLAlchemyError) as error:
        raise _database_unavailable(error) from error

    role = _workspace_role(invitation["workspace_role"])
    return InvitationResponse(
        invitationId=str(new_invitation_id),
        email=str(invitation["normalized_email"]),
        workspaceId=str(workspace_id),
        role=role,
        expiresAt=expires_at,
        activationUrl=_activation_url(token.token, settings),
    )


@router.post(
    "/invitations/{invitation_id}/revoke",
    response_model=InvitationRevokeResponse,
)
async def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: UUID = Query(alias="workspace_id"),
) -> InvitationRevokeResponse:
    """Revoke a pending invitation scoped to the caller's workspace."""
    await _authorize_invitation_admin(current_user, workspace_id)
    actor_id = _actor_uuid(current_user)

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    INVITATION_BY_ID_QUERY,
                    {
                        "invitation_id": invitation_id,
                        "workspace_id": workspace_id,
                    },
                )
                row = result.mappings().first()
                if row is None:
                    raise _auth_error(
                        status.HTTP_404_NOT_FOUND,
                        "auth:invitation_not_found",
                        "The invitation was not found.",
                    )
                if row["used_at"] is not None or row["revoked_at"] is not None:
                    raise _auth_error(
                        status.HTTP_409_CONFLICT,
                        "auth:invitation_not_pending",
                        "The invitation is no longer pending.",
                    )
                await connection.execute(
                    REVOKE_INVITATION_QUERY,
                    {"invitation_id": invitation_id},
                )
                await connection.execute(
                    INSERT_AUTH_AUDIT_QUERY,
                    {
                        "event_type": "auth.invitation_revoked",
                        "user_id": actor_id,
                        "session_id": None,
                        "ip_hash": _metadata_hash(
                            request.client.host if request.client else None,
                            settings,
                        ),
                        "user_agent_hash": _metadata_hash(
                            request.headers.get("user-agent"),
                            settings,
                        ),
                        "metadata": '{"purpose":"invitation"}',
                    },
                )
    except HTTPException:
        raise
    except (RuntimeError, SQLAlchemyError) as error:
        raise _database_unavailable(error) from error

    return InvitationRevokeResponse(invitationId=str(invitation_id), revoked=True)


@auth_router.post("/activate", response_model=LocalSessionResponse)
async def activate_invitation(
    payload: ActivateInvitationRequest,
    request: Request,
    response: Response,
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LocalSessionResponse:
    """Consume an invitation, create a new local account, and start a session."""
    try:
        normalized_password = normalize_password(payload.password)
        password_hash = hash_password(normalized_password)
    except PasswordPolicyError as error:
        raise _auth_error(400, "auth:password_policy", str(error)) from error

    try:
        token_hash = hash_one_time_token(payload.token)
    except ValueError as error:
        raise _auth_error(400, "auth:invitation_invalid", "The invitation is invalid.") from error

    user_id = uuid4()
    member_id = uuid4()
    name = payload.name.strip() if payload.name and payload.name.strip() else None

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                token_result = await connection.execute(
                    ACTIVATION_TOKEN_QUERY,
                    {"token_hash": token_hash},
                )
                invitation = token_result.mappings().first()
                if invitation is None:
                    raise _auth_error(
                        status.HTTP_400_BAD_REQUEST,
                        "auth:invitation_invalid",
                        "The invitation is invalid or expired.",
                    )

                normalized_email = str(invitation["normalized_email"])
                workspace_id = invitation["workspace_id"]
                if workspace_id is None:
                    raise _auth_error(
                        status.HTTP_400_BAD_REQUEST,
                        "auth:invitation_invalid",
                        "The invitation is invalid.",
                    )
                workspace_role = _workspace_role(invitation["workspace_role"])

                await connection.execute(
                    ADVISORY_EMAIL_LOCK_QUERY,
                    {"normalized_email": normalized_email},
                )
                account_result = await connection.execute(
                    EXISTING_LOCAL_ACCOUNT_QUERY,
                    {"normalized_email": normalized_email},
                )
                if account_result.mappings().first() is not None:
                    raise _auth_error(
                        status.HTTP_409_CONFLICT,
                        "auth:account_exists",
                        "A local account already exists for this email.",
                    )

                workspace_result = await connection.execute(
                    INVITATION_WORKSPACE_QUERY,
                    {"workspace_id": workspace_id},
                )
                if workspace_result.mappings().first() is None:
                    raise _auth_error(
                        status.HTTP_400_BAD_REQUEST,
                        "auth:invitation_invalid",
                        "The invitation is invalid.",
                    )

                await connection.execute(
                    INSERT_USER_QUERY,
                    {"user_id": user_id, "email": normalized_email, "name": name},
                )
                await connection.execute(
                    INSERT_PASSWORD_CREDENTIAL_QUERY,
                    {"user_id": user_id, "password_hash": password_hash},
                )
                await connection.execute(
                    INSERT_WORKSPACE_MEMBER_QUERY,
                    {
                        "member_id": member_id,
                        "workspace_role": workspace_role,
                        "user_id": user_id,
                        "workspace_id": workspace_id,
                    },
                )
                await connection.execute(
                    MARK_INVITATION_USED_QUERY,
                    {
                        "invitation_id": invitation["invitation_id"],
                        "user_id": user_id,
                    },
                )
                session = await AuthSessionRepository(connection).create(
                    user_id=user_id,
                    idle_timeout=timedelta(seconds=settings.session_idle_timeout_seconds),
                    absolute_timeout=timedelta(seconds=settings.session_absolute_timeout_seconds),
                    ip_hash=_metadata_hash(
                        request.client.host if request.client else None,
                        settings,
                    ),
                    user_agent_hash=_metadata_hash(
                        request.headers.get("user-agent"),
                        settings,
                    ),
                )
                await connection.execute(
                    INSERT_AUTH_AUDIT_QUERY,
                    {
                        "event_type": "auth.invitation_accepted",
                        "user_id": user_id,
                        "session_id": session.record.session_id,
                        "ip_hash": _metadata_hash(
                            request.client.host if request.client else None,
                            settings,
                        ),
                        "user_agent_hash": _metadata_hash(
                            request.headers.get("user-agent"),
                            settings,
                        ),
                        "metadata": '{"purpose":"invitation"}',
                    },
                )
    except HTTPException:
        raise
    except IntegrityError as error:
        raise _auth_error(
            status.HTTP_409_CONFLICT,
            "auth:activation_conflict",
            "The invitation could not be activated because the account state changed.",
        ) from error
    except (RuntimeError, SQLAlchemyError) as error:
        raise _database_unavailable(error) from error

    _set_session_cookie(response, session.token, request, settings)
    return LocalSessionResponse(
        authenticated=True,
        user={
            "userId": str(user_id),
            "email": normalized_email,
            "name": name,
            "image": None,
        },
    )
