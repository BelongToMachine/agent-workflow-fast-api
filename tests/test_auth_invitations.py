from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.api.routes.auth_invitations as auth_invitations
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.core.one_time_tokens import hash_one_time_token
from app.core.workspace_access import WorkspaceAccess
from app.main import app

client = TestClient(app)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _Mappings:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row

    def all(self):
        if self.row is None:
            return []
        return self.row if isinstance(self.row, list) else [self.row]


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
    def __init__(self, *, invitation=None, invitations=None, existing_account=None):
        self.invitation = invitation
        self.invitations = invitations or []
        self.existing_account = existing_account
        self.calls = []

    def begin(self):
        return _Transaction()

    async def execute(self, query, params):
        sql = str(query)
        self.calls.append((sql, params))
        if 'FROM "Workspace"' in sql:
            return _Result({"id": WORKSPACE_ID})
        if 'FROM "User" AS user_record' in sql and "PasswordCredential" in sql:
            return _Result(self.existing_account)
        if 'ORDER BY "createdAt" DESC' in sql:
            return _Result(self.invitations)
        if 'FROM "AuthOneTimeToken"' in sql:
            return _Result(self.invitation)
        return _Result()


def _settings(*, environment="development") -> Settings:
    return Settings(
        environment=environment,
        auth_mode="dual",
        auth_required=True,
        auth_secret="s" * 32,
        cors_origins="http://localhost:5173",
        auth_frontend_url="http://localhost:5173",
    )


def _admin_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=str(uuid4()),
        claims={"permissions": ["members.manage"]},
        is_development=True,
        role="admin",
    )


def _access() -> WorkspaceAccess:
    return WorkspaceAccess(
        user_id="dev-admin",
        workspace_id=WORKSPACE_ID,
        role="admin",
        permissions=["members.manage"],
        is_guest=False,
        is_development=True,
    )


def _install_overrides(monkeypatch, settings: Settings, user: AuthenticatedUser) -> None:
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[auth_invitations.get_current_user] = lambda: user
    app.dependency_overrides[auth_invitations._require_csrf] = lambda: None
    monkeypatch.setattr(auth_invitations, "require_workspace_permission", _fake_require_access)


async def _fake_require_access(*_args, **_kwargs) -> WorkspaceAccess:
    return _access()


def test_invitation_request_normalizes_and_validates_email() -> None:
    request = auth_invitations.CreateInvitationRequest.model_validate(
        {"email": "  PERSON@Example.COM ", "workspaceId": str(WORKSPACE_ID)}
    )

    assert request.email == "person@example.com"
    assert request.role == "employee"


def test_create_invitation_returns_manual_activation_url(monkeypatch) -> None:
    connection = _Connection()

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_invitations, "get_db_connection", fake_db_connection)
    _install_overrides(monkeypatch, _settings(), _admin_user())
    try:
        response = client.post(
            "/api/v1/admin/auth/invitations",
            json={"email": "person@example.com", "workspaceId": str(WORKSPACE_ID)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "person@example.com"
    assert body["workspaceId"] == str(WORKSPACE_ID)
    assert body["role"] == "employee"
    assert body["activationUrl"].startswith("http://localhost:5173/activate?token=")
    token = body["activationUrl"].split("token=", 1)[1]
    insert_params = next(
        params for sql, params in connection.calls if 'INSERT INTO "AuthOneTimeToken"' in sql
    )
    assert insert_params["token_hash"] == hash_one_time_token(token)
    assert token not in insert_params.values()


def test_manual_invitation_links_are_available_outside_development(monkeypatch) -> None:
    connection = _Connection()

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_invitations, "get_db_connection", fake_db_connection)
    _install_overrides(monkeypatch, _settings(environment="production"), _admin_user())
    try:
        response = client.post(
            "/api/v1/admin/auth/invitations",
            json={"email": "person@example.com", "workspaceId": str(WORKSPACE_ID)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["activationUrl"].startswith("http://localhost:5173/activate?token=")


def test_list_invitations_hides_activation_tokens(monkeypatch) -> None:
    invitation_id = uuid4()
    connection = _Connection(
        invitations=[
            {
                "invitation_id": invitation_id,
                "email": "person@example.com",
                "workspace_id": WORKSPACE_ID,
                "role": "employee",
                "status": "pending",
                "expires_at": datetime.now(UTC).replace(tzinfo=None),
                "created_at": datetime.now(UTC).replace(tzinfo=None),
            }
        ]
    )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_invitations, "get_db_connection", fake_db_connection)
    _install_overrides(monkeypatch, _settings(), _admin_user())
    try:
        response = client.get(
            "/api/v1/admin/auth/invitations",
            params={"workspace_id": str(WORKSPACE_ID)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["invitations"] == [
        {
            "invitationId": str(invitation_id),
            "email": "person@example.com",
            "workspaceId": str(WORKSPACE_ID),
            "role": "employee",
            "status": "pending",
            "expiresAt": response.json()["invitations"][0]["expiresAt"],
            "createdAt": response.json()["invitations"][0]["createdAt"],
        }
    ]
    assert "activationUrl" not in response.json()["invitations"][0]


def test_regenerate_invitation_returns_new_manual_link(monkeypatch) -> None:
    invitation_id = uuid4()
    connection = _Connection(
        invitation={
            "invitation_id": invitation_id,
            "normalized_email": "person@example.com",
            "workspace_id": WORKSPACE_ID,
            "workspace_role": "employee",
            "expires_at": datetime.now(UTC).replace(tzinfo=None),
            "used_at": None,
            "revoked_at": datetime.now(UTC).replace(tzinfo=None),
        }
    )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_invitations, "get_db_connection", fake_db_connection)
    _install_overrides(monkeypatch, _settings(environment="production"), _admin_user())
    try:
        response = client.post(
            f"/api/v1/admin/auth/invitations/{invitation_id}/regenerate",
            params={"workspace_id": str(WORKSPACE_ID)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["invitationId"] != str(invitation_id)
    assert body["activationUrl"].startswith("http://localhost:5173/activate?token=")


def test_activation_consumes_invitation_and_creates_local_account(monkeypatch) -> None:
    invitation_token = "invitation-token"
    connection = _Connection(
        invitation={
            "invitation_id": uuid4(),
            "normalized_email": "person@example.com",
            "workspace_id": WORKSPACE_ID,
            "workspace_role": "employee",
            "expires_at": None,
        }
    )

    class FakeRepository:
        def __init__(self, _connection):
            pass

        async def create(self, **_kwargs):
            return SimpleNamespace(
                token="new-session-token",
                record=SimpleNamespace(session_id=uuid4()),
            )

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(auth_invitations, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(auth_invitations, "AuthSessionRepository", FakeRepository)
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[auth_invitations._require_csrf] = lambda: None
    try:
        response = client.post(
            "/api/v1/auth/activate",
            json={
                "token": invitation_token,
                "password": "a secure activation password",
                "name": "Person",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {
            "userId": response.json()["user"]["userId"],
            "email": "person@example.com",
            "name": "Person",
            "image": None,
        },
    }
    assert "__Host-asianode_session=new-session-token" in response.headers["set-cookie"]
    assert any('INSERT INTO "PasswordCredential"' in sql for sql, _params in connection.calls)
    assert any('INSERT INTO "WorkspaceMember"' in sql for sql, _params in connection.calls)
    used_params = next(params for sql, params in connection.calls if 'SET "usedAt"' in sql)
    assert used_params["user_id"]


def test_invitation_routes_are_disabled_in_logto_mode() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development",
        auth_mode="logto",
        auth_required=True,
    )
    try:
        response = client.post(
            "/api/v1/auth/activate",
            json={"token": "token", "password": "a secure activation password"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
