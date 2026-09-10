from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.api.routes.auth_passwords as auth_passwords
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.core.passwords import hash_password
from app.core.sessions import SESSION_COOKIE_NAME
from app.db.auth_sessions import AuthSessionRecord
from app.main import app

client = TestClient(app)
USER_ID = UUID("00000000-0000-0000-0000-000000000011")


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
    def __init__(self, password_hash: str):
        self.password_hash = password_hash
        self.calls = []

    def begin(self):
        return _Transaction()

    async def execute(self, query, params):
        sql = str(query)
        self.calls.append((sql, params))
        if "FROM \"PasswordCredential\"" in sql:
            return _Result(
                {
                    "password_hash": self.password_hash,
                    "password_version": 1,
                    "user_status": "active",
                    "email": "person@example.com",
                    "name": "Person",
                    "image": None,
                }
            )
        return _Result()


def _settings() -> Settings:
    return Settings(
        environment="development",
        auth_mode="local_session",
        auth_required=True,
        auth_secret="s" * 32,
        cors_origins="http://localhost:3000",
    )


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=str(USER_ID), auth_provider="local")


def test_change_password_requires_a_local_session(monkeypatch) -> None:
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[auth_passwords.get_current_user] = _user
    app.dependency_overrides[auth_passwords._require_csrf] = lambda: None
    try:
        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "currentPassword": "a secure current password",
                "newPassword": "a secure replacement password",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["code"] == "auth:session_required"


def test_change_password_rotates_session_and_revokes_other_sessions(monkeypatch) -> None:
    connection = _Connection(hash_password("a secure current password"))
    old_session_id = uuid4()
    new_session_id = uuid4()
    old_session = AuthSessionRecord(
        session_id=old_session_id,
        user_id=USER_ID,
        token_hash="old-hash",
        created_at=None,  # type: ignore[arg-type]
        last_seen_at=None,  # type: ignore[arg-type]
        idle_expires_at=None,  # type: ignore[arg-type]
        absolute_expires_at=None,  # type: ignore[arg-type]
        revoked_at=None,
        user_status="active",
    )

    class FakeRepository:
        def __init__(self, _connection):
            pass

        async def get_active(self, token, **_kwargs):
            assert token == "old-session-token"
            return old_session

        async def revoke_user_sessions(self, user_id, *, except_session_id=None):
            assert user_id == USER_ID
            assert except_session_id == old_session_id

        async def revoke(self, session_id):
            assert session_id == old_session_id

        async def create(self, **_kwargs):
            return SimpleNamespace(
                token="rotated-session-token",
                record=SimpleNamespace(session_id=new_session_id),
            )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_passwords, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_passwords, "AuthSessionRepository", FakeRepository)
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[auth_passwords.get_current_user] = _user
    app.dependency_overrides[auth_passwords._require_csrf] = lambda: None
    try:
        response = client.post(
            "/api/v1/auth/change-password",
            cookies={SESSION_COOKIE_NAME: "old-session-token"},
            json={
                "currentPassword": "a secure current password",
                "newPassword": "a secure replacement password",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["email"] == "person@example.com"
    assert "__Host-asianode_session=rotated-session-token" in response.headers["set-cookie"]
    assert any("UPDATE \"PasswordCredential\"" in sql for sql, _params in connection.calls)
    assert any("INSERT INTO \"AuthAuditLog\"" in sql for sql, _params in connection.calls)
