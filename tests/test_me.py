from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes.me import _build_memberships
from app.main import app

client = TestClient(app)


def test_development_me_endpoint_returns_explicit_identity() -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json() == {
        "userId": "development-user",
        "email": None,
        "name": None,
        "image": None,
        "status": "active",
        "accessState": "ready",
        "isGuest": False,
        "isDevelopment": True,
        "memberships": [],
    }


def test_effective_permissions_apply_role_defaults_and_overrides() -> None:
    membership_id = UUID("00000000-0000-0000-0000-000000000010")
    workspace_id = UUID("00000000-0000-0000-0000-000000000011")

    memberships = _build_memberships(
        [
            {
                "membership_id": membership_id,
                "workspace_id": workspace_id,
                "workspace_name": "Asianode",
                "role": "viewer",
                "status": "active",
            }
        ],
        [
            {
                "membership_id": membership_id,
                "effect": "grant",
                "permission": "audit.read",
            },
            {
                "membership_id": membership_id,
                "effect": "deny",
                "permission": "chat.write",
            },
        ],
        is_guest=False,
    )

    assert memberships[0].permissions == [
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
    assert memberships[0].overrides[0].permission == "audit.read"


def test_employee_role_can_read_knowledge_but_not_manage_it() -> None:
    membership_id = UUID("00000000-0000-0000-0000-000000000020")
    workspace_id = UUID("00000000-0000-0000-0000-000000000021")

    memberships = _build_memberships(
        [
            {
                "membership_id": membership_id,
                "workspace_id": workspace_id,
                "workspace_name": "Asianode",
                "role": "employee",
                "status": "active",
            }
        ],
        [
            {
                "membership_id": membership_id,
                "effect": "grant",
                "permission": "knowledge.read",
            },
            {
                "membership_id": membership_id,
                "effect": "grant",
                "permission": "knowledge.manage",
            },
        ],
        is_guest=False,
    )

    assert memberships[0].permissions == [
        "knowledge.read",
        "chat.read",
        "chat.write",
        "chat.delete",
        "document.read",
        "document.write",
        "agent.tool.products.search",
        "agent.tool.content.search",
        "agent.tool.knowledge_bases.list",
        "agent.tool.knowledge_files.list",
        "agent.tool.knowledge_base.read",
        "agent.tool.knowledge_file.read",
        "agent.tool.knowledge_base.search",
    ]
