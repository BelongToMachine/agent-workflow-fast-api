import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings, get_settings

JWKS_CACHE_TTL_SECONDS = 300
NEXTAUTH_BRIDGE_TTL_MS = 5 * 60 * 1000
NEXTAUTH_BRIDGE_FUTURE_SKEW_MS = 30 * 1000
NEXTAUTH_BRIDGE_FALLBACK_SECRET = "atlas-trade-copilot-nextauth-bridge"
DEV_DIRECT_TOKEN_TTL_MS = 5 * 60 * 1000
DEV_DIRECT_TOKEN_FUTURE_SKEW_MS = 30 * 1000
DEV_DIRECT_TOKEN_FALLBACK_SECRET = "atlas-trade-copilot-dev-direct"
bearer_scheme = HTTPBearer(auto_error=False)
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    is_guest: bool = False
    is_internal_bridge: bool = False
    claims: dict[str, Any] = Field(default_factory=dict)
    is_development: bool = False


class AuthConfigurationError(Exception):
    """Raised when the service cannot safely validate access tokens."""


class AuthTokenError(Exception):
    """Raised when an access token is malformed, expired, or unverifiable."""


class NextAuthBridgeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email: str | None = None
    is_guest: bool = Field(alias="isGuest", default=False)
    issued_at: int = Field(alias="issuedAt")
    permissions: list[str] = Field(default_factory=list)
    role: str
    subject: str = Field(min_length=1)
    workspace_id: str = Field(alias="workspaceId", min_length=1)


class DevDirectTokenContext(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email: str | None = None
    is_guest: bool = Field(alias="isGuest", default=False)
    issued_at: int = Field(alias="issuedAt")
    permissions: list[str] = Field(default_factory=list)
    role: str
    subject: str = Field(min_length=1)
    workspace_id: str = Field(alias="workspaceId", min_length=1)
    is_development: bool = Field(alias="isDevelopment", default=False)


def _nextauth_bridge_secret(settings: Settings) -> str:
    return (
        settings.nextauth_bridge_secret
        or settings.auth_secret
        or NEXTAUTH_BRIDGE_FALLBACK_SECRET
    )


def _dev_direct_token_secret(settings: Settings) -> str:
    return (
        settings.dev_direct_auth_secret
        or settings.nextauth_bridge_secret
        or settings.auth_secret
        or DEV_DIRECT_TOKEN_FALLBACK_SECRET
    )


def _decode_base64_json(encoded: str) -> dict[str, Any] | None:
    try:
        padding = "=" * (-len(encoded) % 4)
        value = json.loads(
            base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _verify_nextauth_bridge(
    context: str | None,
    signature: str | None,
    settings: Settings,
) -> AuthenticatedUser | None:
    if not context or not signature:
        return None

    expected_signature = base64.urlsafe_b64encode(
        hmac.new(
            _nextauth_bridge_secret(settings).encode("utf-8"),
            context.encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(expected_signature, signature):
        return None

    payload = _decode_base64_json(context)
    if payload is None:
        return None

    try:
        bridge = NextAuthBridgeContext.model_validate(payload)
    except ValidationError:
        return None

    now = int(time.time() * 1000)
    if (
        now - bridge.issued_at > NEXTAUTH_BRIDGE_TTL_MS
        or bridge.issued_at > now + NEXTAUTH_BRIDGE_FUTURE_SKEW_MS
    ):
        return None

    return AuthenticatedUser(
        user_id=bridge.subject,
        email=bridge.email,
        roles=[bridge.role],
        workspace_id=bridge.workspace_id,
        role=bridge.role,
        permissions=bridge.permissions,
        is_guest=bridge.is_guest,
        is_internal_bridge=True,
        claims=payload,
    )


def _verify_dev_direct_token(
    token: str,
    settings: Settings,
) -> AuthenticatedUser | None:
    if settings.environment.strip().lower() != "development" or not token.startswith("dev."):
        return None

    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "dev":
        return None

    encoded_payload, received_signature = parts[1], parts[2]
    expected_signature = base64.urlsafe_b64encode(
        hmac.new(
            _dev_direct_token_secret(settings).encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(expected_signature, received_signature):
        return None

    payload = _decode_base64_json(encoded_payload)
    if payload is None:
        return None

    try:
        direct_token = DevDirectTokenContext.model_validate(payload)
    except ValidationError:
        return None

    now = int(time.time() * 1000)
    if (
        now - direct_token.issued_at > DEV_DIRECT_TOKEN_TTL_MS
        or direct_token.issued_at > now + DEV_DIRECT_TOKEN_FUTURE_SKEW_MS
    ):
        return None

    return AuthenticatedUser(
        user_id=direct_token.subject,
        email=direct_token.email,
        roles=[direct_token.role],
        workspace_id=direct_token.workspace_id,
        role=direct_token.role,
        permissions=direct_token.permissions,
        is_guest=direct_token.is_guest,
        claims=payload,
        is_development=direct_token.is_development,
    )


def create_dev_direct_token(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    issued_at = int(time.time() * 1000)
    token_payload = {**payload, "issuedAt": issued_at, "isDevelopment": True}
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(token_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(
            _dev_direct_token_secret(settings).encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")
    expires_at = issued_at + DEV_DIRECT_TOKEN_TTL_MS
    return {
        "accessToken": f"dev.{encoded_payload}.{signature}",
        "expiresAt": expires_at,
    }


def _auth_is_required(settings: Settings) -> bool:
    return settings.auth_required or settings.environment.lower() in {
        "production",
        "staging",
    }


def _algorithm_list(settings: Settings) -> list[str]:
    algorithms = [item.strip() for item in settings.auth_algorithms.split(",") if item.strip()]
    if not algorithms:
        raise AuthConfigurationError("AUTH_ALGORITHMS must contain at least one algorithm.")
    return algorithms


def _audience_value(settings: Settings) -> str | list[str]:
    if not settings.auth_audience:
        raise AuthConfigurationError("AUTH_AUDIENCE is required for access-token validation.")

    audiences = [item.strip() for item in settings.auth_audience.split(",") if item.strip()]
    if not audiences:
        raise AuthConfigurationError("AUTH_AUDIENCE must contain at least one value.")
    return audiences[0] if len(audiences) == 1 else audiences


def _jwks_url(settings: Settings) -> str:
    if settings.auth_jwks_url:
        return settings.auth_jwks_url
    if not settings.auth_issuer:
        raise AuthConfigurationError("AUTH_ISSUER is required for access-token validation.")

    issuer = settings.auth_issuer.rstrip("/")
    if issuer.endswith("/oidc"):
        return f"{issuer}/jwks"
    return f"{issuer}/.well-known/jwks.json"


async def _fetch_jwks(url: str, *, force_refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    cached = _jwks_cache.get(url)
    if not force_refresh and cached and cached[0] > now:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise AuthTokenError("The JWKS endpoint could not be reached.") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise AuthTokenError("The JWKS endpoint returned an invalid key set.")

    _jwks_cache[url] = (now + JWKS_CACHE_TTL_SECONDS, payload)
    return payload


async def _signing_key(token: str, settings: Settings) -> Any:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as error:
        raise AuthTokenError("The access token header is invalid.") from error

    algorithms = _algorithm_list(settings)
    if header.get("alg") not in algorithms:
        raise AuthTokenError("The access token algorithm is not allowed.")

    key_id = header.get("kid")
    if not isinstance(key_id, str) or not key_id:
        raise AuthTokenError("The access token is missing a key identifier.")

    url = _jwks_url(settings)
    key_set = await _fetch_jwks(url)
    jwk = next(
        (key for key in key_set["keys"] if isinstance(key, dict) and key.get("kid") == key_id),
        None,
    )
    if jwk is None:
        key_set = await _fetch_jwks(url, force_refresh=True)
        jwk = next(
            (key for key in key_set["keys"] if isinstance(key, dict) and key.get("kid") == key_id),
            None,
        )
    if jwk is None:
        raise AuthTokenError("The access token signing key was not found.")

    try:
        return jwt.PyJWK.from_dict(jwk).key
    except (TypeError, ValueError, jwt.PyJWTError) as error:
        raise AuthTokenError("The access token signing key is invalid.") from error


def _user_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise AuthTokenError("The access token is missing a subject.")

    raw_roles = claims.get("roles", [])
    if isinstance(raw_roles, str):
        roles = [raw_roles]
    elif isinstance(raw_roles, list):
        roles = [str(role) for role in raw_roles if isinstance(role, str)]
    else:
        roles = []

    workspace_id = (
        claims.get("workspace_id") or claims.get("workspaceId") or claims.get("organization_id")
    )
    is_guest = bool(claims.get("isGuest") or claims.get("is_guest") or "guest" in roles)
    return AuthenticatedUser(
        user_id=user_id,
        email=claims.get("email") if isinstance(claims.get("email"), str) else None,
        roles=roles,
        workspace_id=workspace_id if isinstance(workspace_id, str) else None,
        is_guest=is_guest,
        claims=claims,
    )


async def verify_access_token(token: str, settings: Settings) -> AuthenticatedUser:
    if not settings.auth_issuer:
        raise AuthConfigurationError("AUTH_ISSUER is required for access-token validation.")

    key = await _signing_key(token, settings)
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=_algorithm_list(settings),
            audience=_audience_value(settings),
            issuer=settings.auth_issuer,
            options={"require": ["sub", "iss", "aud", "exp"]},
            leeway=30,
        )
    except jwt.PyJWTError as error:
        raise AuthTokenError("The access token is invalid or expired.") from error

    if not isinstance(claims, dict):
        raise AuthTokenError("The access token claims are invalid.")
    return _user_from_claims(claims)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
    x_asianode_auth_context: str | None = Header(default=None),
    x_asianode_auth_signature: str | None = Header(default=None),
) -> AuthenticatedUser:
    if credentials is None:
        bridge_context = (
            x_asianode_auth_context if isinstance(x_asianode_auth_context, str) else None
        )
        bridge_signature = (
            x_asianode_auth_signature if isinstance(x_asianode_auth_signature, str) else None
        )
        if bridge_context or bridge_signature:
            bridge_user = _verify_nextauth_bridge(
                bridge_context,
                bridge_signature,
                settings,
            )
            if bridge_user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Internal authentication context is invalid or expired.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return bridge_user

        if _auth_is_required(settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer access token is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthenticatedUser(user_id="development-user", is_development=True)

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        direct_user = _verify_dev_direct_token(credentials.credentials, settings)
        if direct_user is not None:
            return direct_user
        return await verify_access_token(credentials.credentials, settings)
    except AuthConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured correctly.",
        ) from error
    except AuthTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
