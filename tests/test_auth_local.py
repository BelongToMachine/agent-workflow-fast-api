from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.api.routes.auth_local as auth_local
from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


class _Mappings:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _Mappings(self._row)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Connection:
    def __init__(self, row):
        self.row = row

    def begin(self):
        return _Transaction()

    async def execute(self, query, _params):
        query_text = str(query)
        if "PasswordCredential" in query_text:
            return _Result(self.row)
        return _Result(self.row)


def _settings() -> Settings:
    return Settings(
        environment="development",
        auth_mode="dual",
        auth_required=True,
        auth_secret="s" * 32,
        cors_origins="http://localhost:3000",
    )


def test_local_auth_endpoints_are_disabled_in_logto_mode() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development",
        auth_mode="logto",
        auth_required=True,
        cors_origins="http://localhost:3000",
    )
    try:
        response = client.get("/api/v1/auth/session")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 404


def test_local_login_requires_an_exact_origin_and_csrf_token() -> None:
    app.dependency_overrides[get_settings] = _settings
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "person@example.com",
                "password": "a secure password with enough length",
            },
            headers={"Origin": "https://evil.example"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 403
    assert response.json()["code"] == "csrf:origin_invalid"


def test_loopback_development_csrf_cookie_is_secure() -> None:
    app.dependency_overrides[get_settings] = _settings
    try:
        response = client.get(
            "/api/v1/auth/csrf",
            headers={
                "Origin": "http://localhost:3000",
                "Host": "localhost",
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert "; Secure" in response.headers["set-cookie"]


def test_local_login_sets_an_opaque_httponly_session_cookie(monkeypatch) -> None:
    user_id = uuid4()
    row = {
        "user_id": user_id,
        "email": "person@example.com",
        "name": "Person",
        "image": None,
        "status": "active",
    }
    # Use a real hash so this test exercises the same verification path as production.
    from app.core.passwords import hash_password

    row["password_hash"] = hash_password("a secure password with enough length")
    connection = _Connection(row)

    class FakeRepository:
        def __init__(self, received_connection):
            assert received_connection is connection

        async def create(self, **_kwargs):
            return SimpleNamespace(token="opaque-session-token")

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_local, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_local, "AuthSessionRepository", FakeRepository)
    app.dependency_overrides[get_settings] = _settings
    try:
        csrf_response = client.get(
            "/api/v1/auth/csrf",
            headers={"Origin": "http://localhost:3000"},
        )
        csrf_token = csrf_response.json()["csrfToken"]
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "PERSON@example.com",
                "password": "a secure password with enough length",
            },
            headers={
                "Origin": "http://localhost:3000",
                "X-CSRF-Token": csrf_token,
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {
            "userId": str(user_id),
            "email": "person@example.com",
            "name": "Person",
            "image": None,
        },
    }
    cookie = response.headers["set-cookie"]
    assert "__Host-asianode_session=opaque-session-token" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie
