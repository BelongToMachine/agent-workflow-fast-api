from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

import app.api.routes.auth_bootstrap as auth_bootstrap
from app.api.routes.me import CurrentUserResponse
from app.core.auth import AuthenticatedUser, ExternalPrincipal
from app.main import app

client = TestClient(app)


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeConnection:
    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()


def test_bootstrap_requires_a_bearer_token() -> None:
    response = client.post("/api/v1/auth/bootstrap")

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer access token is required."


def test_bootstrap_returns_the_initialized_business_identity(monkeypatch) -> None:
    principal = ExternalPrincipal(
        subject="logto|external-user-123",
        issuer="https://tenant.logto.app/oidc",
        email="person@example.com",
        name="Person",
        roles=["user"],
    )
    connection = _FakeConnection()
    local_user = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        external_subject=principal.subject,
        auth_provider="logto",
        email=principal.email,
        claims=principal.claims,
    )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    async def fake_bootstrap(received_connection, received_principal):
        assert received_connection is connection
        assert received_principal == principal
        return local_user

    async def fake_response(received_connection, received_user):
        assert received_connection is connection
        assert received_user == local_user
        return CurrentUserResponse(
            userId=local_user.user_id,
            email=local_user.email,
            name="Person",
            status="active",
            accessState="pending_workspace",
            memberships=[],
        )

    monkeypatch.setattr(auth_bootstrap, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_bootstrap, "bootstrap_external_identity", fake_bootstrap)
    monkeypatch.setattr(auth_bootstrap, "build_current_user_response", fake_response)
    app.dependency_overrides[auth_bootstrap.get_external_principal] = lambda: principal
    try:
        response = client.post(
            "/api/v1/auth/bootstrap",
            headers={"Authorization": "Bearer logto-token"},
        )
    finally:
        app.dependency_overrides.pop(auth_bootstrap.get_external_principal, None)

    assert response.status_code == 200
    assert response.json()["userId"] == local_user.user_id
    assert response.json()["accessState"] == "pending_workspace"
    assert response.json()["memberships"] == []
