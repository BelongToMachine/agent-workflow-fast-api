import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import app.db.provision_local_admin as provision_local_admin
from app.core.config import Settings

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


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
    def __init__(self, *, account=None):
        self.account = account
        self.calls = []

    def begin(self):
        return _Transaction()

    async def execute(self, query, params):
        sql = str(query)
        self.calls.append((sql, params))
        if 'FROM "Workspace"' in sql:
            return _Result({"id": WORKSPACE_ID, "name": "Asianode"})
        if 'FROM "User" AS user_record' in sql:
            return _Result(self.account)
        return _Result()


def _settings() -> Settings:
    return Settings(
        environment="development",
        auth_mode="local_session",
        default_workspace_id=WORKSPACE_ID,
        auth_secret="s" * 32,
    )


def test_provision_local_admin_is_preflight_by_default(monkeypatch, capsys) -> None:
    connection = _Connection()

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(provision_local_admin, "get_settings", _settings)
    monkeypatch.setattr(provision_local_admin, "get_db_connection", fake_db_connection)

    result = asyncio.run(
        provision_local_admin._provision(
            email=" Owner@Example.COM ",
            name="Owner",
            workspace_id=WORKSPACE_ID,
            confirmed=False,
        )
    )

    assert result == 2
    assert "Preflight only" in capsys.readouterr().out
    assert not any('INSERT INTO "User"' in sql for sql, _ in connection.calls)


def test_provision_local_admin_creates_owner_without_command_line_password(
    monkeypatch,
) -> None:
    connection = _Connection()

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(provision_local_admin, "get_settings", _settings)
    monkeypatch.setattr(provision_local_admin, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(provision_local_admin, "_read_password", lambda: "a secure owner password")

    result = asyncio.run(
        provision_local_admin._provision(
            email="owner@example.com",
            name="Owner",
            workspace_id=WORKSPACE_ID,
            confirmed=True,
        )
    )

    assert result == 0
    assert any('INSERT INTO "User"' in sql for sql, _ in connection.calls)
    credential_params = next(
        params
        for sql, params in connection.calls
        if 'INSERT INTO "PasswordCredential"' in sql
    )
    assert credential_params["password_hash"].startswith("$argon2")
    assert any("'owner'" in sql for sql, _ in connection.calls)
    assert any("auth.local_admin_provisioned" in sql for sql, _ in connection.calls)


def test_provision_local_admin_refuses_non_development(monkeypatch) -> None:
    settings = Settings(environment="staging", auth_mode="local_session")
    monkeypatch.setattr(provision_local_admin, "get_settings", lambda: settings)

    result = asyncio.run(
        provision_local_admin._provision(
            email="owner@example.com",
            name=None,
            workspace_id=WORKSPACE_ID,
            confirmed=True,
        )
    )

    assert result == 1
