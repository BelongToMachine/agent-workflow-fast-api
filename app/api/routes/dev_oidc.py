import base64
import hashlib
import hmac
import json
import time
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.auth import create_dev_direct_token
from app.core.config import Settings, get_settings
from app.core.permissions import DEFAULT_PERMISSIONS_BY_ROLE, PERMISSION_CATALOG

router = APIRouter(prefix="/dev/oidc", tags=["dev-oidc"])

DEV_OIDC_CODE_TTL_MS = 5 * 60 * 1000
DEV_OIDC_FUTURE_SKEW_MS = 30 * 1000
DEV_OIDC_FALLBACK_SECRET = "atlas-trade-copilot-dev-oidc"
DEV_OIDC_STANDARD_SCOPES = ("openid", "profile", "email")
LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


class DevOidcConsentRequest(BaseModel):
    client_id: str = Field(alias="clientId", min_length=1, max_length=100)
    permissions: list[str] = Field(default_factory=list, max_length=len(PERMISSION_CATALOG))
    redirect_uri: str = Field(alias="redirectUri", min_length=1, max_length=2048)
    scopes: list[str] = Field(default_factory=list, max_length=len(DEV_OIDC_STANDARD_SCOPES))
    state: str | None = Field(default=None, max_length=512)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("client_id", "redirect_uri", mode="before")
    @classmethod
    def trim_required_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("permissions", "scopes")
    @classmethod
    def reject_duplicates(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Duplicate value")
        return values

    @field_validator("scopes")
    @classmethod
    def validate_standard_scopes(cls, values: list[str]) -> list[str]:
        if any(scope not in DEV_OIDC_STANDARD_SCOPES for scope in values):
            raise ValueError("Unknown scope")
        return values

    @model_validator(mode="after")
    def validate_openid_scope(self) -> "DevOidcConsentRequest":
        if "openid" not in self.scopes:
            raise ValueError("The openid scope is required.")
        return self


class DevOidcBridgeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    subject: str = Field(min_length=1)
    email: str | None = None
    permissions: list[str] = Field(default_factory=list)
    workspace_id: str = Field(alias="workspaceId", min_length=1)
    is_guest: bool = Field(alias="isGuest", default=False)
    issued_at: int = Field(alias="issuedAt")


class DevDirectTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email: str | None = Field(default=None, max_length=320)
    is_guest: bool = Field(alias="isGuest", default=False)
    permissions: list[str] = Field(default_factory=list, max_length=len(PERMISSION_CATALOG))
    role: Literal["owner", "admin", "editor", "viewer"] = "viewer"
    subject: str = Field(min_length=1, max_length=100)
    workspace_id: str = Field(alias="workspaceId", min_length=1, max_length=100)

    @field_validator("permissions")
    @classmethod
    def reject_duplicate_permissions(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Duplicate permission")
        return values


def _secret(settings: Settings, *, bridge: bool = False) -> str:
    if bridge and settings.dev_oidc_internal_secret:
        return settings.dev_oidc_internal_secret
    return settings.auth_secret or DEV_OIDC_FALLBACK_SECRET


def _encode_json(value: dict[str, Any]) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).rstrip(b"=").decode("ascii")


def _decode_json(encoded: str) -> dict[str, Any] | None:
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sign(encoded: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_signed_json(
    encoded: str | None, signature: str | None, secret: str
) -> dict[str, Any] | None:
    if not encoded or not signature:
        return None
    expected = _sign(encoded, secret)
    if not hmac.compare_digest(expected, signature):
        return None
    return _decode_json(encoded)


def _verify_bridge_context(
    encoded_context: str | None,
    signature: str | None,
    settings: Settings,
) -> DevOidcBridgeContext | None:
    payload = _verify_signed_json(encoded_context, signature, _secret(settings, bridge=True))
    if payload is None:
        return None

    try:
        context = DevOidcBridgeContext.model_validate(payload)
    except ValidationError:
        return None

    now = int(time.time() * 1000)
    if (
        now - context.issued_at > DEV_OIDC_CODE_TTL_MS
        or context.issued_at > now + DEV_OIDC_FUTURE_SKEW_MS
    ):
        return None
    return context


def normalize_dev_redirect_uri(
    value: str | None, request_url: str = "http://localhost"
) -> str | None:
    if not value:
        return "/dev/oidc/result"

    if not value.startswith("/") and not value.lower().startswith(("http://", "https://")):
        return None

    try:
        parsed = urlparse(urljoin(request_url, value))
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in LOOPBACK_HOSTNAMES
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            return None

        if value.startswith("/"):
            return urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
        return parsed.geturl()
    except ValueError:
        return None


def create_dev_oidc_code(payload: dict[str, Any], settings: Settings) -> str:
    code_payload = {**payload, "issuedAt": int(time.time() * 1000)}
    encoded_payload = _encode_json(code_payload)
    return f"{encoded_payload}.{_sign(encoded_payload, _secret(settings))}"


def verify_dev_oidc_code(code: str, settings: Settings) -> dict[str, Any] | None:
    encoded_payload, separator, encoded_signature = code.partition(".")
    if not separator:
        return None

    payload = _verify_signed_json(encoded_payload, encoded_signature, _secret(settings))
    if payload is None:
        return None

    issued_at = payload.get("issuedAt")
    if not isinstance(issued_at, int):
        return None

    now = int(time.time() * 1000)
    if now - issued_at > DEV_OIDC_CODE_TTL_MS or issued_at > now + DEV_OIDC_FUTURE_SKEW_MS:
        return None
    return payload


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"message": message}, status_code=status_code)


@router.post("/consent")
async def create_consent_code(
    request: Request,
    settings: Settings = Depends(get_settings),
    x_asianode_dev_oidc_context: str | None = Header(default=None),
    x_asianode_dev_oidc_signature: str | None = Header(default=None),
) -> JSONResponse:
    if settings.environment.lower() != "development":
        return _error("Not Found", 404)

    actor = _verify_bridge_context(
        x_asianode_dev_oidc_context,
        x_asianode_dev_oidc_signature,
        settings,
    )
    if actor is None:
        return _error("Sign in is required.", 401)

    try:
        input_data = DevOidcConsentRequest.model_validate(await request.json())
    except (TypeError, ValueError, ValidationError):
        return _error("Invalid OIDC consent request.", 400)

    unknown_permissions = set(input_data.permissions).difference(PERMISSION_CATALOG)
    if unknown_permissions:
        return _error("The request contains an unknown permission.", 400)

    if any(permission not in actor.permissions for permission in input_data.permissions):
        return _error("You cannot grant a permission your account does not have.", 403)

    redirect_uri = normalize_dev_redirect_uri(input_data.redirect_uri, str(request.url))
    if not redirect_uri:
        return _error("Redirect URIs must point to a local development host.", 400)

    code_payload: dict[str, Any] = {
        "clientId": input_data.client_id,
        "email": actor.email,
        "permissions": input_data.permissions,
        "redirectUri": redirect_uri,
        "scopes": input_data.scopes,
        "subject": actor.subject,
        "workspaceId": actor.workspace_id,
    }
    if input_data.state is not None:
        code_payload["state"] = input_data.state

    code = create_dev_oidc_code(code_payload, settings)
    redirect_url = urljoin(str(request.url), redirect_uri)
    redirect_parts = urlparse(redirect_url)
    query = parse_qsl(redirect_parts.query, keep_blank_values=True)
    query.append(("code", code))
    if input_data.state is not None:
        query.append(("state", input_data.state))

    redirect_url = urlunparse(
        redirect_parts._replace(query=urlencode(query), fragment="")
    )

    return JSONResponse(
        {
            "expiresIn": DEV_OIDC_CODE_TTL_MS // 1000,
            "redirectUrl": redirect_url,
            "scope": " ".join([*input_data.scopes, *input_data.permissions]),
        }
    )


@router.post("/token")
async def create_development_token(
    payload: DevDirectTokenRequest,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if settings.environment.lower() != "development":
        return _error("Not Found", 404)

    unknown_permissions = set(payload.permissions).difference(PERMISSION_CATALOG)
    if unknown_permissions:
        return _error("The request contains an unknown permission.", 400)

    token = create_dev_direct_token(
        {
            "email": payload.email,
            "isGuest": payload.is_guest,
            "permissions": payload.permissions,
            "role": payload.role,
            "subject": payload.subject,
            "workspaceId": payload.workspace_id,
        },
        settings,
    )
    return JSONResponse(
        {
            **token,
            "workspaceId": payload.workspace_id,
            "role": payload.role,
            "permissions": payload.permissions,
            "isGuest": payload.is_guest,
            "defaults": list(DEFAULT_PERMISSIONS_BY_ROLE[payload.role]),
        }
    )
