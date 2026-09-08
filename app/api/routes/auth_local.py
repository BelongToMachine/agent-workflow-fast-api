"""Local password and browser-session authentication endpoints.

These endpoints are intentionally small: the browser receives only an opaque
session cookie, while password hashes and session records stay in PostgreSQL.
The Logto bootstrap endpoint remains available for the migration's dual-auth
mode until the local account migration is complete.
"""

from __future__ import annotations

import unicodedata
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    generate_csrf_token,
    is_allowed_origin,
    validate_csrf_token,
)
from app.core.passwords import (
    MIN_PASSWORD_LENGTH,
    dummy_password_hash,
    verify_and_update_password,
    verify_password,
)
from app.core.sessions import (
    SESSION_COOKIE_NAME,
    hash_client_metadata,
)
from app.db.auth_sessions import AuthSessionRepository
from app.db.session import get_db_connection


class LocalLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class LocalSessionUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    email: str | None = None
    name: str | None = None
    image: str | None = None


class LocalSessionResponse(BaseModel):
    authenticated: bool
    user: LocalSessionUser | None = None


LOGIN_USER_QUERY = text(
    """
    SELECT
        user_record."id" AS user_id,
        user_record."email" AS email,
        user_record."name" AS name,
        user_record."image" AS image,
        user_record."status" AS status,
        credential."passwordHash" AS password_hash
    FROM "User" AS user_record
    LEFT JOIN "PasswordCredential" AS credential
        ON credential."userId" = user_record."id"
    WHERE lower(user_record."email") = :normalized_email
    LIMIT 1
    """
)

USER_BY_ID_QUERY = text(
    """
    SELECT
        "id" AS user_id,
        "email" AS email,
        "name" AS name,
        "image" AS image,
        "status" AS status
    FROM "User"
    WHERE "id" = :user_id
    LIMIT 1
    """
)

UPDATE_PASSWORD_HASH_QUERY = text(
    """
    UPDATE "PasswordCredential"
    SET "passwordHash" = :password_hash,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "userId" = :user_id
    """
)


def normalize_email(email: str) -> str:
    """Normalize the login lookup key without changing the stored profile."""
    return unicodedata.normalize("NFC", email).strip().casefold()


def _allowed_origins(settings: Settings) -> list[str]:
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


def _ensure_local_auth_mode(settings: Settings = Depends(get_settings)) -> None:
    if settings.auth_mode not in {"dual", "local_session"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local session authentication is disabled.",
        )


router = APIRouter(
    prefix="/auth",
    tags=["local-auth"],
    dependencies=[Depends(_ensure_local_auth_mode)],
)


def _require_allowed_origin(request: Request, settings: Settings) -> None:
    if not is_allowed_origin(request.headers.get("origin"), _allowed_origins(settings)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "csrf:origin_invalid",
                "message": "Request origin is not allowed.",
            },
        )


def _secure_cookie(request: Request, settings: Settings) -> bool:
    # Local development commonly runs over HTTP. Staging/production must keep
    # Secure even when the application sees an HTTP origin behind a tunnel.
    return request.url.scheme == "https" or settings.environment in {"staging", "production"}


def _set_csrf_cookie(response: Response, token: str, request: Request, settings: Settings) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=3600,
        httponly=False,
        secure=_secure_cookie(request, settings),
        samesite="lax",
        path="/",
    )


def _set_session_cookie(
    response: Response,
    token: str,
    request: Request,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_absolute_timeout_seconds,
        httponly=True,
        secure=_secure_cookie(request, settings),
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response, request: Request, settings: Settings) -> None:
    secure = _secure_cookie(request, settings)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", secure=secure, samesite="lax")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/", secure=secure, samesite="lax")


def _require_csrf(
    request: Request,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    _require_allowed_origin(request, settings)
    csrf_header = request.headers.get(CSRF_HEADER_NAME)
    if not validate_csrf_token(csrf_cookie, csrf_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "csrf:token_invalid",
                "message": "CSRF token is missing or invalid.",
            },
        )


def _metadata_hash(value: str | None, settings: Settings) -> str | None:
    if not value or not settings.auth_secret:
        return None
    return hash_client_metadata(value, pepper=settings.auth_secret)


def _session_user_from_row(row: dict[str, object]) -> LocalSessionUser:
    return LocalSessionUser(
        userId=str(row["user_id"]),
        email=row["email"] if isinstance(row["email"], str) else None,
        name=row["name"] if isinstance(row["name"], str) else None,
        image=row["image"] if isinstance(row["image"], str) else None,
    )


async def _load_session_user(connection: object, user_id: UUID) -> LocalSessionUser | None:
    result = await connection.execute(USER_BY_ID_QUERY, {"user_id": user_id})
    row = result.mappings().first()
    if row is None or row["status"] != "active":
        return None
    return _session_user_from_row(dict(row))


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email or password is incorrect.",
        headers={"WWW-Authenticate": "Session"},
    )


def _verify_login_password(password: str, password_hash: object) -> tuple[bool, str | None]:
    if isinstance(password_hash, str) and password_hash:
        return verify_and_update_password(password, password_hash)

    # Keep unknown-user checks on the Argon2 path even when the submitted
    # password is too short for the normal policy validator.
    dummy_password = password
    if len(unicodedata.normalize("NFC", dummy_password)) < MIN_PASSWORD_LENGTH:
        dummy_password = "x" * MIN_PASSWORD_LENGTH
    return verify_password(dummy_password, dummy_password_hash()), None


@router.get("/csrf")
async def get_csrf_token(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Issue a short-lived double-submit CSRF token for browser mutations."""
    token = generate_csrf_token()
    _set_csrf_cookie(response, token, request, settings)
    return {"csrfToken": token}


@router.post("/login", response_model=LocalSessionResponse)
async def login_local_user(
    payload: LocalLoginRequest,
    request: Request,
    response: Response,
    _: None = Depends(_require_csrf),
    settings: Settings = Depends(get_settings),
) -> LocalSessionResponse:
    """Verify a local password and create an opaque browser session."""
    normalized_email = normalize_email(payload.email)
    row: dict[str, object] | None = None
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                result = await connection.execute(
                    LOGIN_USER_QUERY,
                    {"normalized_email": normalized_email},
                )
                raw_row = result.mappings().first()
                if raw_row is not None:
                    row = dict(raw_row)

                password_hash = row.get("password_hash") if row else None
                valid, replacement_hash = _verify_login_password(
                    payload.password,
                    password_hash,
                )
                if not valid or row is None:
                    raise _invalid_credentials()
                if row["status"] != "active":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="user:suspended",
                    )

                user_id = UUID(str(row["user_id"]))
                if replacement_hash:
                    await connection.execute(
                        UPDATE_PASSWORD_HASH_QUERY,
                        {"user_id": user_id, "password_hash": replacement_hash},
                    )
                session = await AuthSessionRepository(connection).create(
                    user_id=user_id,
                    idle_timeout=timedelta(seconds=settings.session_idle_timeout_seconds),
                    absolute_timeout=timedelta(seconds=settings.session_absolute_timeout_seconds),
                    ip_hash=_metadata_hash(
                        request.client.host if request.client else None,
                        settings,
                    ),
                    user_agent_hash=_metadata_hash(request.headers.get("user-agent"), settings),
                )
    except HTTPException:
        raise
    except (ValueError, RuntimeError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication storage is unavailable.",
        ) from error

    _set_session_cookie(response, session.token, request, settings)
    return LocalSessionResponse(authenticated=True, user=_session_user_from_row(row))


@router.get("/session", response_model=LocalSessionResponse)
async def read_local_session(
    request: Request,
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    settings: Settings = Depends(get_settings),
) -> LocalSessionResponse:
    """Return the current local browser session without exposing its token."""
    if not session_token:
        return LocalSessionResponse(authenticated=False)

    try:
        async with get_db_connection() as connection:
            session = await AuthSessionRepository(connection).get_active(session_token)
            if session is None:
                _clear_auth_cookies(response, request, settings)
                return LocalSessionResponse(authenticated=False)
            user = await _load_session_user(connection, session.user_id)
    except (ValueError, RuntimeError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication storage is unavailable.",
        ) from error

    if user is None:
        _clear_auth_cookies(response, request, settings)
        return LocalSessionResponse(authenticated=False)
    return LocalSessionResponse(authenticated=True, user=user)


@router.post("/logout", response_model=LocalSessionResponse)
async def logout_local_user(
    request: Request,
    response: Response,
    _: None = Depends(_require_csrf),
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    settings: Settings = Depends(get_settings),
) -> LocalSessionResponse:
    """Revoke the current session and clear browser authentication cookies."""
    try:
        if session_token:
            async with get_db_connection() as connection:
                async with connection.begin():
                    session = await AuthSessionRepository(connection).get_active(session_token)
                    if session is not None:
                        await AuthSessionRepository(connection).revoke(session.session_id)
    except (ValueError, RuntimeError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication storage is unavailable.",
        ) from error

    _clear_auth_cookies(response, request, settings)
    return LocalSessionResponse(authenticated=False)
