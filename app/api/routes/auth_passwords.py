"""Local password change endpoint."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.auth_invitations import INSERT_AUTH_AUDIT_QUERY
from app.api.routes.auth_local import (
    LocalSessionResponse,
    _ensure_local_auth_mode,
    _metadata_hash,
    _require_csrf,
    _set_session_cookie,
)
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.passwords import (
    PasswordPolicyError,
    hash_password,
    normalize_password,
    verify_password,
)
from app.core.sessions import SESSION_COOKIE_NAME
from app.db.auth_sessions import AuthSessionRepository
from app.db.session import get_db_connection


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    current_password: str = Field(alias="currentPassword", min_length=1, max_length=1024)
    new_password: str = Field(alias="newPassword", min_length=1, max_length=1024)


PASSWORD_QUERY = text(
    """
    SELECT
        credential."passwordHash" AS password_hash,
        credential."passwordVersion" AS password_version,
        user_record."status" AS user_status,
        user_record."email" AS email,
        user_record."name" AS name,
        user_record."image" AS image
    FROM "PasswordCredential" AS credential
    INNER JOIN "User" AS user_record
        ON user_record."id" = credential."userId"
    WHERE credential."userId" = :user_id
    FOR UPDATE
    """
)

UPDATE_PASSWORD_QUERY = text(
    """
    UPDATE "PasswordCredential"
    SET "passwordHash" = :password_hash,
        "passwordVersion" = "passwordVersion" + 1,
        "passwordChangedAt" = CURRENT_TIMESTAMP,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "userId" = :user_id
    """
)


router = APIRouter(
    prefix="/auth",
    tags=["local-auth"],
    dependencies=[Depends(_ensure_local_auth_mode)],
)


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@router.post("/change-password", response_model=LocalSessionResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> LocalSessionResponse:
    """Change a password and rotate the current browser session."""
    if not session_token:
        raise _auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth:session_required",
            "A local browser session is required.",
        )

    try:
        normalized_new_password = normalize_password(payload.new_password)
        replacement_hash = hash_password(normalized_new_password)
        user_id = UUID(current_user.user_id)
    except PasswordPolicyError as error:
        raise _auth_error(400, "auth:password_policy", str(error)) from error
    except ValueError as error:
        raise _auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth:session_invalid",
            "The local browser session is invalid.",
        ) from error

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                sessions = AuthSessionRepository(connection)
                session = await sessions.get_active(
                    session_token,
                    absolute_timeout_seconds=settings.session_absolute_timeout_seconds,
                )
                if session is None or session.user_id != user_id:
                    raise _auth_error(
                        status.HTTP_401_UNAUTHORIZED,
                        "auth:session_invalid",
                        "The local browser session is invalid.",
                    )

                password_result = await connection.execute(
                    PASSWORD_QUERY,
                    {"user_id": user_id},
                )
                credential = password_result.mappings().first()
                if credential is None or credential["user_status"] != "active":
                    raise _auth_error(
                        status.HTTP_409_CONFLICT,
                        "auth:credential_missing",
                        "A local password has not been configured.",
                    )
                if not verify_password(payload.current_password, str(credential["password_hash"])):
                    raise _auth_error(
                        status.HTTP_400_BAD_REQUEST,
                        "auth:current_password_invalid",
                        "The current password is incorrect.",
                    )

                await connection.execute(
                    UPDATE_PASSWORD_QUERY,
                    {"user_id": user_id, "password_hash": replacement_hash},
                )
                await sessions.revoke_user_sessions(
                    user_id,
                    except_session_id=session.session_id,
                )
                await sessions.revoke(session.session_id)
                replacement_session = await sessions.create(
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
                        "event_type": "auth.password_changed",
                        "user_id": user_id,
                        "session_id": replacement_session.record.session_id,
                        "ip_hash": _metadata_hash(
                            request.client.host if request.client else None,
                            settings,
                        ),
                        "user_agent_hash": _metadata_hash(
                            request.headers.get("user-agent"),
                            settings,
                        ),
                        "metadata": '{"method":"current_password"}',
                    },
                )
    except HTTPException:
        raise
    except (RuntimeError, SQLAlchemyError) as error:
        raise _auth_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "auth:storage_unavailable",
            "Authentication storage is unavailable.",
        ) from error

    _set_session_cookie(response, replacement_session.token, request, settings)
    return LocalSessionResponse(
        authenticated=True,
        user={
            "userId": str(user_id),
            "email": credential["email"],
            "name": credential["name"],
            "image": credential["image"],
        },
    )
