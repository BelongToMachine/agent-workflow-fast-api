from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.admin_members import (
    CreateMemberRequest,
    UpdateMemberRequest,
    UpdateMemberStatusRequest,
    _build_member_views,
    _permission_overrides,
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
        "agent.tool.products.search",
        "agent.tool.content.search",
        "agent.tool.knowledge_bases.list",
        "agent.tool.knowledge_files.list",
        "agent.tool.knowledge_base.read",
        "agent.tool.knowledge_file.read",
        "agent.tool.knowledge_base.search",
    ]
    assert views[0].is_custom_role is True
    assert views[0].model_dump(by_alias=True)["isCustomRole"] is True
    assert views[0].user_id == "00000000-0000-0000-0000-000000000011"


def test_member_views_mark_standard_role_permissions_as_not_custom() -> None:
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
        [],
    )

    assert views[0].is_custom_role is False
    assert views[0].model_dump(by_alias=True)["isCustomRole"] is False


def test_member_views_apply_agent_tool_permission_denials() -> None:
    member_id = UUID("00000000-0000-0000-0000-000000000010")
    views = _build_member_views(
        [
            {
                "id": member_id,
                "role": "employee",
                "status": "active",
                "user_id": UUID("00000000-0000-0000-0000-000000000011"),
                "workspace_id": UUID("00000000-0000-0000-0000-000000000012"),
                "email": "employee@example.com",
                "name": "Employee",
                "workspace_name": "Asianode",
            }
        ],
        [
            {
                "member_id": member_id,
                "effect": "deny",
                "permission": "agent.tool.knowledge.search",
            }
        ],
    )

    assert "agent.tool.knowledge.search" not in views[0].effective_permissions


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


def test_update_request_accepts_employee_role() -> None:
    request = UpdateMemberRequest.model_validate(
        {
            "memberId": "00000000-0000-0000-0000-000000000010",
            "permissions": [
                "chat.read",
                "chat.write",
                "chat.delete",
                "document.read",
                "document.write",
            ],
            "role": "employee",
        }
    )

    assert request.role == "employee"


def test_update_request_accepts_agent_tool_permissions() -> None:
    request = UpdateMemberRequest.model_validate(
        {
            "memberId": "00000000-0000-0000-0000-000000000010",
            "permissions": ["agent.tool.knowledge_base.search"],
            "role": "employee",
        }
    )

    assert request.permissions == ["agent.tool.knowledge_base.search"]


def test_member_permission_overrides_can_grant_file_extraction_only_to_one_member() -> None:
    overrides = _permission_overrides(
        "employee",
        ["knowledge.read", "agent.tool.knowledge_file.extract"],
    )

    assert {
        (item["effect"], item["permission"])
        for item in overrides
    } >= {
        ("grant", "agent.tool.knowledge_file.extract"),
        ("deny", "agent.tool.knowledge_base.search"),
    }


def test_create_request_defaults_permissions_to_role_baseline() -> None:
    request = CreateMemberRequest.model_validate(
        {
            "userId": "00000000-0000-0000-0000-000000000011",
            "role": "employee",
        }
    )

    assert request.permissions is None
    assert request.role == "employee"


def test_create_request_preserves_explicit_initial_permissions() -> None:
    request = CreateMemberRequest.model_validate(
        {
            "userId": "00000000-0000-0000-0000-000000000011",
            "role": "employee",
            "permissions": ["knowledge.read"],
        }
    )

    assert "knowledge.read" in request.permissions


def test_member_status_request_only_accepts_supported_states() -> None:
    assert (
        UpdateMemberStatusRequest.model_validate({"status": "suspended"}).status
        == "suspended"
    )
    with pytest.raises(ValidationError):
        UpdateMemberStatusRequest.model_validate({"status": "deleted"})


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
