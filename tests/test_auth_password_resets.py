from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.api.routes.auth_password_resets as auth_password_resets
from app.core.config import Settings, get_settings
from app.core.one_time_tokens import hash_one_time_token
from app.core.sessions import SESSION_COOKIE_NAME
from app.main import app

client = TestClient(app)
USER_ID = UUID("00000000-0000-0000-0000-000000000012")


class _Mappings:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return _Mappings(self.row)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Connection:
    def __init__(self, *, account=None, token_row=None):
        self.account = account
        self.token_row = token_row
        self.calls = []

    def begin(self):
        return _Transaction()

    async def execute(self, query, params):
        sql = str(query)
        self.calls.append((sql, params))
        if "FROM \"User\" AS user_record" in sql and "PasswordCredential" in sql:
            if "user_record.\"id\" =" in sql:
                return _Result(self.account)
            return _Result(self.account)
        if "FROM \"AuthOneTimeToken\"" in sql and '"tokenHash"' in sql:
            return _Result(self.token_row)
        return _Result()


def _settings() -> Settings:
    return Settings(
        environment="development",
        auth_mode="local_session",
        auth_required=True,
        auth_secret="s" * 32,
        cors_origins="http://localhost:3000",
        auth_frontend_url="http://localhost:3000",
        auth_password_reset_ttl_seconds=3600,
    )


def test_password_reset_request_returns_dev_only_manual_url(monkeypatch) -> None:
    connection = _Connection(
        account={
            "user_id": USER_ID,
            "email": "person@example.com",
            "name": "Person",
            "image": None,
            "status": "active",
        }
    )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_password_resets, "get_db_connection", fake_db_connection)
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[auth_password_resets._require_csrf] = lambda: None
    try:
        response = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": " PERSON@Example.COM "},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["requested"] is True
    assert body["resetUrl"].startswith("http://localhost:3000/reset-password?token=")
    token = body["resetUrl"].split("token=", 1)[1]
    insert_params = next(
        params
        for sql, params in connection.calls
        if 'INSERT INTO "AuthOneTimeToken"' in sql
    )
    assert insert_params["token_hash"] == hash_one_time_token(token)
    assert token not in insert_params.values()


def test_password_reset_request_does_not_reveal_unknown_account(monkeypatch) -> None:
    connection = _Connection(account=None)

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_password_resets, "get_db_connection", fake_db_connection)
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[auth_password_resets._require_csrf] = lambda: None
    try:
        response = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "unknown@example.com"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"requested": True, "resetUrl": None}
    assert not any('INSERT INTO "AuthOneTimeToken"' in sql for sql, _ in connection.calls)


def test_password_reset_confirmation_rotates_session(monkeypatch) -> None:
    reset_token = "reset-token"
    connection = _Connection(
        account={
            "user_id": USER_ID,
            "email": "person@example.com",
            "name": "Person",
            "image": None,
            "status": "active",
        },
        token_row={
            "token_id": uuid4(),
            "user_id": USER_ID,
            "normalized_email": "person@example.com",
        },
    )
    new_session_id = uuid4()

    class FakeRepository:
        def __init__(self, _connection):
            pass

        async def revoke_user_sessions(self, user_id):
            assert user_id == USER_ID

        async def create(self, **_kwargs):
            return SimpleNamespace(
                token="reset-session-token",
                record=SimpleNamespace(session_id=new_session_id),
            )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_password_resets, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_password_resets, "AuthSessionRepository", FakeRepository)
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[auth_password_resets._require_csrf] = lambda: None
    try:
        response = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "token": reset_token,
                "newPassword": "a secure reset password",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["email"] == "person@example.com"
    assert f"{SESSION_COOKIE_NAME}=reset-session-token" in response.headers["set-cookie"]
    assert any('UPDATE "PasswordCredential"' in sql for sql, _ in connection.calls)
    assert any('SET "usedAt"' in sql for sql, _ in connection.calls)
    assert any('INSERT INTO "AuthAuditLog"' in sql for sql, _ in connection.calls)


def test_password_reset_routes_are_disabled_in_logto_mode() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development",
        auth_mode="logto",
        auth_required=True,
    )
    try:
        response = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "person@example.com"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
