"""Development password-reset request and confirmation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.routes.auth_invitations import INSERT_AUTH_AUDIT_QUERY
from app.api.routes.auth_local import (
    LocalSessionResponse,
    _ensure_local_auth_mode,
    _metadata_hash,
    _require_csrf,
    _set_session_cookie,
    normalize_email,
)
from app.core.config import Settings, get_settings
from app.core.one_time_tokens import hash_one_time_token, new_one_time_token
from app.core.passwords import PasswordPolicyError, hash_password, normalize_password
from app.db.auth_sessions import AuthSessionRepository
from app.db.session import get_db_connection


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class PasswordResetRequestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requested: bool
    reset_url: str | None = Field(default=None, alias="resetUrl")


class ConfirmPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(alias="newPassword", min_length=1, max_length=1024)


ACCOUNT_BY_EMAIL_QUERY = text(
    """
    SELECT
        user_record."id" AS user_id,
        user_record."email" AS email,
        user_record."name" AS name,
        user_record."image" AS image,
        user_record."status" AS status
    FROM "User" AS user_record
    INNER JOIN "PasswordCredential" AS credential
        ON credential."userId" = user_record."id"
    WHERE lower(btrim(user_record."email")) = :normalized_email
    LIMIT 1
    FOR UPDATE
    """
)

REVOKE_PENDING_PASSWORD_RESETS_QUERY = text(
    """
    UPDATE "AuthOneTimeToken"
    SET "revokedAt" = CURRENT_TIMESTAMP
    WHERE "normalizedEmail" = :normalized_email
      AND "purpose" = 'password_reset'
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
    """
)

INSERT_PASSWORD_RESET_QUERY = text(
    """
    INSERT INTO "AuthOneTimeToken" (
        "id", "userId", "normalizedEmail", "purpose", "tokenHash",
        "expiresAt", "createdAt"
    )
    VALUES (
        :token_id, :user_id, :normalized_email, 'password_reset', :token_hash,
        :expires_at, CURRENT_TIMESTAMP
    )
    """
)

RESET_TOKEN_QUERY = text(
    """
    SELECT
        "id" AS token_id,
        "userId" AS user_id,
        "normalizedEmail" AS normalized_email
    FROM "AuthOneTimeToken"
    WHERE "tokenHash" = :token_hash
      AND "purpose" = 'password_reset'
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
      AND "expiresAt" > CURRENT_TIMESTAMP
    FOR UPDATE
    """
)

RESET_ACCOUNT_QUERY = text(
    """
    SELECT
        user_record."id" AS user_id,
        user_record."email" AS email,
        user_record."name" AS name,
        user_record."image" AS image,
        user_record."status" AS status
    FROM "User" AS user_record
    INNER JOIN "PasswordCredential" AS credential
        ON credential."userId" = user_record."id"
    WHERE user_record."id" = :user_id
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

MARK_RESET_USED_QUERY = text(
    """
    UPDATE "AuthOneTimeToken"
    SET "usedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :token_id
      AND "usedAt" IS NULL
      AND "revokedAt" IS NULL
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


def _reset_url(token: str, settings: Settings) -> str:
    return f"{settings.auth_frontend_url.rstrip('/')}/reset-password?token={quote(token, safe='')}"


def _storage_error(error: Exception) -> HTTPException:
    return _auth_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "auth:storage_unavailable",
        "Authentication storage is unavailable.",
    )


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PasswordResetRequestResponse:
    """Request a password reset.

    Until an email adapter exists, only development returns a manual URL. The
    response remains generic for unknown addresses to avoid account probing.
    """
    if settings.environment != "development":
        raise _auth_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "auth:password_reset_delivery_unavailable",
            "Password reset email delivery is not configured.",
        )

    token = new_one_time_token()
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=settings.auth_password_reset_ttl_seconds
    )
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                account_result = await connection.execute(
                    ACCOUNT_BY_EMAIL_QUERY,
                    {"normalized_email": payload.email},
                )
                account = account_result.mappings().first()
                if account is None or account["status"] != "active":
                    return PasswordResetRequestResponse(requested=True)

                user_id = UUID(str(account["user_id"]))
                await connection.execute(
                    REVOKE_PENDING_PASSWORD_RESETS_QUERY,
                    {"normalized_email": payload.email},
                )
                await connection.execute(
                    INSERT_PASSWORD_RESET_QUERY,
                    {
                        "token_id": uuid4(),
                        "user_id": user_id,
                        "normalized_email": payload.email,
                        "token_hash": token.token_hash,
                        "expires_at": expires_at,
                    },
                )
                await connection.execute(
                    INSERT_AUTH_AUDIT_QUERY,
                    {
                        "event_type": "auth.password_reset_requested",
                        "user_id": user_id,
                        "session_id": None,
                        "ip_hash": _metadata_hash(
                            request.client.host if request.client else None,
                            settings,
                        ),
                        "user_agent_hash": _metadata_hash(
                            request.headers.get("user-agent"),
                            settings,
                        ),
                        "metadata": '{"delivery":"manual_development_url"}',
                    },
                )
    except HTTPException:
        raise
    except (ValueError, IntegrityError, RuntimeError, SQLAlchemyError) as error:
        raise _storage_error(error) from error

    return PasswordResetRequestResponse(requested=True, resetUrl=_reset_url(token.token, settings))


@router.post("/password-reset/confirm", response_model=LocalSessionResponse)
async def confirm_password_reset(
    payload: ConfirmPasswordResetRequest,
    request: Request,
    response: Response,
    _: Annotated[None, Depends(_require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LocalSessionResponse:
    """Consume a password-reset token and start a fresh browser session."""
    try:
        normalized_password = normalize_password(payload.new_password)
        password_hash = hash_password(normalized_password)
        token_hash = hash_one_time_token(payload.token)
    except (PasswordPolicyError, ValueError) as error:
        raise _auth_error(
            status.HTTP_400_BAD_REQUEST,
            "auth:password_reset_invalid",
            "The password reset link is invalid or expired.",
        ) from error

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                token_result = await connection.execute(
                    RESET_TOKEN_QUERY,
                    {"token_hash": token_hash},
                )
                token_row = token_result.mappings().first()
                if token_row is None or token_row["user_id"] is None:
                    raise _auth_error(
                        status.HTTP_400_BAD_REQUEST,
                        "auth:password_reset_invalid",
                        "The password reset link is invalid or expired.",
                    )

                user_id = UUID(str(token_row["user_id"]))
                account_result = await connection.execute(
                    RESET_ACCOUNT_QUERY,
                    {"user_id": user_id},
                )
                account = account_result.mappings().first()
                if account is None or account["status"] != "active":
                    raise _auth_error(
                        status.HTTP_400_BAD_REQUEST,
                        "auth:password_reset_invalid",
                        "The password reset link is invalid or expired.",
                    )

                await connection.execute(
                    UPDATE_PASSWORD_QUERY,
                    {"user_id": user_id, "password_hash": password_hash},
                )
                await connection.execute(
                    MARK_RESET_USED_QUERY,
                    {"token_id": token_row["token_id"]},
                )
                sessions = AuthSessionRepository(connection)
                await sessions.revoke_user_sessions(user_id)
                session = await sessions.create(
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
                        "event_type": "auth.password_reset_completed",
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
                        "metadata": '{"method":"one_time_token"}',
                    },
                )
    except HTTPException:
        raise
    except (ValueError, RuntimeError, SQLAlchemyError) as error:
        raise _storage_error(error) from error

    _set_session_cookie(response, session.token, request, settings)
    return LocalSessionResponse(
        authenticated=True,
        user={
            "userId": str(user_id),
            "email": account["email"],
            "name": account["name"],
            "image": account["image"],
        },
    )
