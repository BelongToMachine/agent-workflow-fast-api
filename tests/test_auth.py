import asyncio
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import app.core.auth as auth
from app.core.auth import AuthenticatedUser, AuthTokenError, get_current_user
from app.core.config import Settings


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

    assert user.user_id == "user-123"
    assert user.roles == ["employee"]
    assert user.workspace_id == "workspace-123"
    assert user.is_development is False


def test_verify_access_token_rejects_a_tampered_token(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"
    settings = Settings(
        auth_issuer="https://issuer.example.com/oidc",
        auth_audience="api://asianode",
        auth_jwks_url="https://issuer.example.com/oidc/jwks",
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
