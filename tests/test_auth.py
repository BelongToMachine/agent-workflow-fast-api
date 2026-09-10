import asyncio
import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.security import HTTPAuthorizationCredentials

import app.core.auth as auth
import app.db.auth_sessions as auth_sessions
from app.core.auth import (
    AuthenticatedUser,
    AuthTokenError,
    ExternalPrincipal,
    get_current_user,
)
from app.core.config import Settings


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Connection:
    def begin(self):
        return _Transaction()


def test_development_mode_has_an_explicit_non_production_identity() -> None:
    settings = Settings(environment="development", auth_required=False)

    user = asyncio.run(get_current_user(None, settings))

    assert user == AuthenticatedUser(user_id="development-user", is_development=True)


def test_production_requires_authentication_by_default() -> None:
    settings = Settings(environment="production", auth_required=False)

    try:
        asyncio.run(get_current_user(None, settings))
    except Exception as error:
        assert getattr(error, "status_code", None) == 401
    else:
        raise AssertionError("Production authentication must not silently allow anonymous access.")


def test_dual_mode_prefers_a_valid_local_session(monkeypatch) -> None:
    settings = Settings(environment="development", auth_mode="dual", auth_required=True)
    record = auth_sessions.AuthSessionRecord(
        session_id=uuid4(),
        user_id=uuid4(),
        token_hash="a" * 64,
        created_at=datetime(2026, 1, 1),
        last_seen_at=datetime(2026, 1, 1),
        idle_expires_at=datetime(2026, 1, 2),
        absolute_expires_at=datetime(2026, 1, 8),
        revoked_at=None,
        user_status="active",
    )

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection

        async def get_active(self, token: str, **_kwargs):
            assert token == "opaque-session-token"
            return record

        async def touch_if_due(self, received_record, **_kwargs):
            assert received_record is record
            return True

    @asynccontextmanager
    async def fake_db_connection():
        yield _Connection()

    monkeypatch.setattr(auth, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_sessions, "AuthSessionRepository", FakeRepository)

    user = asyncio.run(
        auth.get_current_user(
            None,
            settings,
            "opaque-session-token",
        )
    )

    assert user.user_id == str(record.user_id)
    assert user.auth_provider == "local"


def test_local_session_mode_rejects_missing_cookie_when_required() -> None:
    settings = Settings(environment="production", auth_mode="local_session")

    try:
        asyncio.run(auth.get_current_user(None, settings, None))
    except Exception as error:
        assert getattr(error, "status_code", None) == 401
        assert getattr(error, "detail", None) == "Session cookie is required."
    else:
        raise AssertionError("Local session mode must require a session cookie.")


def test_dual_mode_rejects_an_invalid_local_session_cookie(monkeypatch) -> None:
    settings = Settings(environment="development", auth_mode="dual", auth_required=True)

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection

        async def get_active(self, token: str, **_kwargs):
            assert token == "invalid-session-token"
            return None

    @asynccontextmanager
    async def fake_db_connection():
        yield _Connection()

    monkeypatch.setattr(auth, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_sessions, "AuthSessionRepository", FakeRepository)

    try:
        asyncio.run(auth.get_current_user(None, settings, "invalid-session-token"))
    except Exception as error:
        assert getattr(error, "status_code", None) == 401
        assert getattr(error, "detail", None) == "Session cookie is invalid or expired."
    else:
        raise AssertionError("An invalid local session cookie must be rejected.")


def test_verify_access_token_checks_oidc_claims_and_jwks(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"
    settings = Settings(
        environment="production",
        auth_required=True,
        auth_issuer="https://issuer.example.com/oidc",
        auth_audience="api://asianode",
        auth_jwks_url="https://issuer.example.com/oidc/jwks",
        auth_algorithms="RS256",
    )
    token = jwt.encode(
        {
            "sub": "user-123",
            "email": "user@example.com",
            "roles": ["employee"],
            "workspaceId": "workspace-123",
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
            "exp": int(time.time()) + 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    async def fake_fetch_jwks(url: str, *, force_refresh: bool = False):
        assert url == settings.auth_jwks_url
        return {"keys": [public_jwk]}

    monkeypatch.setattr(auth, "_fetch_jwks", fake_fetch_jwks)
    user = asyncio.run(auth.verify_access_token(token, settings))

    assert isinstance(user, ExternalPrincipal)
    assert user.subject == "user-123"
    assert user.issuer == settings.auth_issuer
    assert user.email == "user@example.com"
    assert user.roles == ["employee"]
    assert user.claims["workspaceId"] == "workspace-123"


def test_verify_access_token_rejects_a_tampered_token(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"
    settings = Settings(
        auth_issuer="https://issuer.example.com/oidc",
        auth_audience="api://asianode",
        auth_jwks_url="https://issuer.example.com/oidc/jwks",
        auth_algorithms="RS256",
    )
    token = jwt.encode(
        {
            "sub": "user-123",
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
            "exp": int(time.time()) + 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    async def fake_fetch_jwks(url: str, *, force_refresh: bool = False):
        return {"keys": [public_jwk]}

    monkeypatch.setattr(auth, "_fetch_jwks", fake_fetch_jwks)
    tampered_token = f"{token.rsplit('.', 1)[0]}.invalid-signature"

    try:
        asyncio.run(auth.verify_access_token(tampered_token, settings))
    except AuthTokenError:
        pass
    else:
        raise AssertionError("A tampered access token must be rejected.")


def test_development_direct_token_is_accepted() -> None:
    settings = Settings(
        environment="development",
        auth_mode="dual",
        auth_required=True,
        dev_direct_auth_secret="direct-secret",
    )
    payload = {
        "email": "user@example.com",
        "isGuest": False,
        "issuedAt": int(time.time() * 1000),
        "permissions": ["chat.read", "chat.write"],
        "role": "editor",
        "subject": "user-123",
        "workspaceId": "workspace-123",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(
            settings.dev_direct_auth_secret.encode(),
            encoded.encode(),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode()

    user = asyncio.run(
        get_current_user(
            HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=f"dev.{encoded}.{signature}",
            ),
            settings,
        )
    )

    assert user.user_id == "user-123"
    assert user.workspace_id == "workspace-123"
    assert user.permissions == ["chat.read", "chat.write"]
    assert user.is_development is False
