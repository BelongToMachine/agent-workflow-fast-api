import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.api.routes.dev_oidc import (
    DEV_OIDC_STANDARD_SCOPES,
    _encode_json,
    _sign,
    verify_dev_oidc_code,
)
from app.core.config import Settings, get_settings
from app.core.permissions import PERMISSION_CATALOG
from app.main import app

client = TestClient(app)


def _bridge_headers(settings: Settings, permissions: list[str] | None = None) -> dict[str, str]:
    payload = {
        "email": "employee@example.com",
        "isGuest": False,
        "issuedAt": int(time.time() * 1000),
        "permissions": permissions or list(PERMISSION_CATALOG),
        "subject": "user-123",
        "workspaceId": "workspace-123",
    }
    encoded = _encode_json(payload)
    secret = settings.dev_oidc_internal_secret or settings.auth_secret
    assert secret is not None
    return {
        "x-asianode-dev-oidc-context": encoded,
        "x-asianode-dev-oidc-signature": _sign(encoded, secret),
    }


@pytest.fixture
def dev_settings():
    settings = Settings(
        environment="development",
        auth_secret="code-secret",
        dev_oidc_internal_secret="bridge-secret",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def test_consent_code_is_compatible_with_next_oidc_verifier(dev_settings: Settings) -> None:
    response = client.post(
        "/api/v1/dev/oidc/consent",
        headers=_bridge_headers(dev_settings),
        json={
            "clientId": "next-local-client",
            "permissions": ["knowledge.read", "chat.write"],
            "redirectUri": "http://localhost:3000/dev/oidc/result?source=local",
            "scopes": list(DEV_OIDC_STANDARD_SCOPES),
            "state": "state-123",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["expiresIn"] == 300
    assert result["scope"] == "openid profile email knowledge.read chat.write"

    query = parse_qs(urlparse(result["redirectUrl"]).query)
    code_payload = verify_dev_oidc_code(query["code"][0], dev_settings)

    assert code_payload is not None
    assert code_payload["clientId"] == "next-local-client"
    assert code_payload["subject"] == "user-123"
    assert code_payload["workspaceId"] == "workspace-123"
    assert code_payload["redirectUri"] == (
        "http://localhost:3000/dev/oidc/result?source=local"
    )
    assert query["state"] == ["state-123"]


def test_consent_requires_the_signed_next_auth_context(dev_settings: Settings) -> None:
    response = client.post(
        "/api/v1/dev/oidc/consent",
        json={
            "clientId": "local-client",
            "permissions": [],
            "redirectUri": "http://localhost:3000/dev/oidc/result",
            "scopes": ["openid"],
        },
    )

    assert response.status_code == 401
    assert response.json() == {"message": "Sign in is required."}


@pytest.mark.parametrize(
    ("body", "status_code", "message"),
    [
        (
            {
                "clientId": "local-client",
                "permissions": ["not-a-permission"],
                "redirectUri": "http://localhost:3000/dev/oidc/result",
                "scopes": ["openid"],
            },
            400,
            "The request contains an unknown permission.",
        ),
        (
            {
                "clientId": "local-client",
                "permissions": ["chat.write"],
                "redirectUri": "http://localhost:3000/dev/oidc/result",
                "scopes": ["openid"],
            },
            403,
            "You cannot grant a permission your account does not have.",
        ),
        (
            {
                "clientId": "local-client",
                "permissions": [],
                "redirectUri": "https://evil.example.com/callback",
                "scopes": ["openid"],
            },
            400,
            "Redirect URIs must point to a local development host.",
        ),
    ],
)
def test_consent_rejects_invalid_or_unauthorized_requests(
    dev_settings: Settings,
    body: dict[str, object],
    status_code: int,
    message: str,
) -> None:
    headers = _bridge_headers(dev_settings, permissions=["knowledge.read"])
    response = client.post("/api/v1/dev/oidc/consent", headers=headers, json=body)

    assert response.status_code == status_code
    assert response.json() == {"message": message}


def test_consent_route_is_disabled_outside_development(dev_settings: Settings) -> None:
    production_settings = Settings(
        environment="production",
        auth_secret="code-secret",
        dev_oidc_internal_secret="bridge-secret",
    )
    app.dependency_overrides[get_settings] = lambda: production_settings

    response = client.post("/api/v1/dev/oidc/consent")

    assert response.status_code == 404
    assert response.json() == {"message": "Not Found"}
