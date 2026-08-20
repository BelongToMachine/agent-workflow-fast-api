import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.admin_members import (
    UpdateMemberRequest,
    _build_member_views,
    _require_non_anonymous_development_identity,
)
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def development_settings():
    settings = Settings(
        environment="development",
        auth_secret="code-secret",
        nextauth_bridge_secret="bridge-secret",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def test_member_views_include_role_defaults_and_overrides() -> None:
    member_id = UUID("00000000-0000-0000-0000-000000000010")
    views = _build_member_views(
        [
            {
                "id": member_id,
                "role": "viewer",
                "status": "active",
                "user_id": UUID("00000000-0000-0000-0000-000000000011"),
                "workspace_id": UUID("00000000-0000-0000-0000-000000000012"),
                "email": "viewer@example.com",
                "name": "Viewer",
                "workspace_name": "Asianode",
            }
        ],
        [
            {
                "member_id": member_id,
                "effect": "grant",
                "permission": "audit.read",
            },
            {
                "member_id": member_id,
                "effect": "deny",
                "permission": "chat.write",
            },
        ],
    )

    assert views[0].effective_permissions == [
        "knowledge.read",
        "chat.read",
        "document.read",
        "audit.read",
    ]
    assert views[0].user_id == "00000000-0000-0000-0000-000000000011"


def test_update_request_rejects_unknown_or_duplicate_permissions() -> None:
    with pytest.raises(ValidationError):
        UpdateMemberRequest.model_validate(
            {
                "memberId": "00000000-0000-0000-0000-000000000010",
                "permissions": ["not-a-permission"],
                "role": "viewer",
            }
        )

    with pytest.raises(ValidationError):
        UpdateMemberRequest.model_validate(
            {
                "memberId": "00000000-0000-0000-0000-000000000010",
                "permissions": ["chat.read", "chat.read"],
                "role": "viewer",
            }
        )


def test_admin_endpoint_does_not_accept_anonymous_development_identity(
    development_settings: Settings,
) -> None:
    response = client.get(
        "/api/v1/admin/members",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401


def test_admin_guard_accepts_a_development_oidc_identity() -> None:
    _require_non_anonymous_development_identity(
        AuthenticatedUser(
            user_id="dev-admin",
            is_development=True,
            claims={"permissions": ["members.manage"]},
        )
    )


def test_admin_guard_rejects_anonymous_development_identity() -> None:
    with pytest.raises(HTTPException) as error:
        _require_non_anonymous_development_identity(
            AuthenticatedUser(user_id="development-user", is_development=True)
        )

    assert error.value.status_code == 401


def test_nextauth_bridge_context_is_accepted_for_authenticated_requests(
    development_settings: Settings,
) -> None:
    context = {
        "email": "admin@example.com",
        "isGuest": False,
        "issuedAt": int(time.time() * 1000),
        "permissions": ["members.read", "members.manage"],
        "role": "admin",
        "subject": "00000000-0000-0000-0000-000000000010",
        "workspaceId": "00000000-0000-0000-0000-000000000001",
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(context, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(
            development_settings.nextauth_bridge_secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")

    response = client.get(
        "/api/v1/admin/members",
        params={"workspace_id": context["workspaceId"]},
        headers={
            "x-asianode-auth-context": encoded,
            "x-asianode-auth-signature": signature,
        },
    )

    assert response.status_code != 401
