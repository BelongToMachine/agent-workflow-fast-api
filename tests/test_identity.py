import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.core.auth as auth
from app.core.auth import ExternalPrincipal
from app.core.config import Settings
from app.core.identity import (
    ExternalIdentityNotInitialized,
    UserSuspended,
    bootstrap_external_identity,
    resolve_external_identity,
)


class _FakeMappings:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def first(self) -> dict[str, object] | None:
        return self._row


class _FakeResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._row)


class _FakeConnection:
    def __init__(
        self,
        row: dict[str, object] | None,
        *,
        existing_user_id: UUID | None = None,
    ) -> None:
        self.row = row
        self.existing_user_id = existing_user_id
        self.params: dict[str, object] | None = None
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, query: object, params: dict[str, object]) -> _FakeResult:
        self.params = params
        sql = str(query)
        self.calls.append((sql, params))
        if 'INSERT INTO "ExternalIdentity"' in sql:
            user_id = self.existing_user_id or params["user_id"]
            return _FakeResult({"user_id": user_id})
        return _FakeResult(self.row)


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _BootstrapConnection(_FakeConnection):
    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, query: object, params: dict[str, object]) -> _FakeResult:
        sql = str(query)
        self.params = params
        self.calls.append((sql, params))
        if 'INSERT INTO "ExternalIdentity"' in sql:
            user_id = self.existing_user_id or params["user_id"]
            return _FakeResult({"user_id": user_id})
        if 'SELECT\n        "id" AS user_id' in sql:
            user_id = self.existing_user_id or params["user_id"]
            row = self.row or {}
            return _FakeResult(
                {
                    "user_id": user_id,
                    "email": row.get("email"),
                    "is_anonymous": row.get("is_anonymous", False),
                    "status": row.get("status", "active"),
                }
            )
        return _FakeResult(self.row)


def _principal() -> ExternalPrincipal:
    return ExternalPrincipal(
        subject="logto|external-user-123",
        issuer="https://tenant.logto.app/oidc",
        email="person@example.com",
        roles=["user"],
        claims={"sub": "logto|external-user-123"},
    )


def test_external_identity_resolves_external_subject_to_local_user() -> None:
    connection = _FakeConnection(
        {
            "provider": "logto",
            "subject": "logto|external-user-123",
            "user_id": UUID("00000000-0000-0000-0000-000000000010"),
            "email": None,
            "is_anonymous": False,
            "user_status": "active",
        }
    )

    user = asyncio.run(resolve_external_identity(connection, _principal()))

    assert user.user_id == "00000000-0000-0000-0000-000000000010"
    assert user.external_subject == "logto|external-user-123"
    assert user.auth_provider == "logto"
    assert user.email is None
    assert connection.params == {
        "provider": "logto",
        "subject": "logto|external-user-123",
    }


def test_external_identity_requires_bootstrap() -> None:
    connection = _FakeConnection(None)

    with pytest.raises(ExternalIdentityNotInitialized):
        asyncio.run(resolve_external_identity(connection, _principal()))


def test_suspended_local_user_is_rejected() -> None:
    connection = _FakeConnection(
        {
            "provider": "logto",
            "subject": "logto|external-user-123",
            "user_id": UUID("00000000-0000-0000-0000-000000000010"),
            "email": "person@example.com",
            "is_anonymous": False,
            "user_status": "suspended",
        }
    )

    with pytest.raises(UserSuspended):
        asyncio.run(resolve_external_identity(connection, _principal()))


def test_real_access_token_is_resolved_to_local_identity(monkeypatch) -> None:
    settings = Settings(
        environment="production",
        auth_required=True,
        auth_issuer="https://tenant.logto.app/oidc",
        auth_audience="https://api.asianode.example.com",
    )
    connection = _FakeConnection(
        {
            "provider": "logto",
            "subject": "logto|external-user-123",
            "user_id": UUID("00000000-0000-0000-0000-000000000010"),
            "email": "person@example.com",
            "is_anonymous": False,
            "user_status": "active",
        }
    )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    async def fake_verify_access_token(_token: str, _settings: Settings) -> ExternalPrincipal:
        return _principal()

    monkeypatch.setattr(auth, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth, "verify_access_token", fake_verify_access_token)

    user = asyncio.run(
        auth.get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="logto-token"),
            settings,
        )
    )

    assert user.user_id == "00000000-0000-0000-0000-000000000010"
    assert user.external_subject == "logto|external-user-123"


def test_uninitialized_real_access_token_returns_structured_forbidden(monkeypatch) -> None:
    settings = Settings(
        environment="production",
        auth_required=True,
        auth_issuer="https://tenant.logto.app/oidc",
        auth_audience="https://api.asianode.example.com",
    )
    connection = _FakeConnection(None)

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    async def fake_verify_access_token(_token: str, _settings: Settings) -> ExternalPrincipal:
        return _principal()

    monkeypatch.setattr(auth, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth, "verify_access_token", fake_verify_access_token)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            auth.get_current_user(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="logto-token"),
                settings,
            )
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "auth_identity:not_initialized"


def test_bootstrap_creates_a_local_user_without_workspace_membership() -> None:
    connection = _BootstrapConnection(
        {"email": None, "is_anonymous": False, "status": "active"}
    )
    principal = _principal().model_copy(
        update={"email": None, "name": "WeChat user", "picture": None}
    )

    user = asyncio.run(bootstrap_external_identity(connection, principal))

    assert user.auth_provider == "logto"
    assert user.external_subject == principal.subject
    assert UUID(user.user_id)
    assert any('INSERT INTO "User"' in sql for sql, _params in connection.calls)
    assert any('INSERT INTO "ExternalIdentity"' in sql for sql, _params in connection.calls)


def test_bootstrap_reuses_the_existing_local_user() -> None:
    local_user_id = UUID("00000000-0000-0000-0000-000000000010")
    connection = _BootstrapConnection(
        {"email": "old@example.com", "is_anonymous": False, "status": "active"},
        existing_user_id=local_user_id,
    )

    user = asyncio.run(bootstrap_external_identity(connection, _principal()))

    assert user.user_id == str(local_user_id)
    assert any('DELETE FROM "User"' in sql for sql, _params in connection.calls)
    update_params = next(
        params for sql, params in connection.calls if 'UPDATE "User"' in sql
    )
    assert update_params["user_id"] == local_user_id


def test_bootstrap_rejects_a_suspended_local_user() -> None:
    connection = _BootstrapConnection(
        {"email": "person@example.com", "is_anonymous": False, "status": "suspended"}
    )

    with pytest.raises(UserSuspended):
        asyncio.run(bootstrap_external_identity(connection, _principal()))
