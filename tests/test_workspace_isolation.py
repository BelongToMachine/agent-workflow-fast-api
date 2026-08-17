import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api.routes.knowledge_bases import KnowledgeBaseListResponse, list_knowledge_bases
from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.core.workspace_access import require_workspace_permission

WORKSPACE_A = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_B = UUID("00000000-0000-0000-0000-000000000002")
USER_A = UUID("00000000-0000-0000-0000-000000000010")
MEMBERSHIP_A = UUID("00000000-0000-0000-0000-000000000011")
KNOWLEDGE_BASE_A = UUID("00000000-0000-0000-0000-000000000020")


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def first(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, results: list[list[dict[str, object]]]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.results = iter(results)

    async def execute(self, query: object, params: dict[str, object]) -> FakeResult:
        self.calls.append((str(query), params))
        return FakeResult(next(self.results))


def connection_context(connection: FakeConnection):
    @asynccontextmanager
    async def context():
        yield connection

    return context


def test_member_lookup_is_scoped_to_requested_workspace(monkeypatch) -> None:
    connection = FakeConnection([[]])
    monkeypatch.setattr(
        "app.core.workspace_access.get_db_connection",
        connection_context(connection),
    )
    user = AuthenticatedUser(user_id=str(USER_A))

    with pytest.raises(HTTPException) as error:
        asyncio.run(require_workspace_permission(user, WORKSPACE_B, "knowledge.read"))

    assert error.value.status_code == 403
    assert "no active membership" in str(error.value.detail)
    assert connection.calls[0][1] == {
        "user_id": USER_A,
        "workspace_id": WORKSPACE_B,
    }


def test_role_permission_override_is_enforced_before_returning_workspace_access(
    monkeypatch,
) -> None:
    connection = FakeConnection(
        [
            [
                {
                    "membership_id": MEMBERSHIP_A,
                    "role": "editor",
                    "is_anonymous": False,
                }
            ],
            [{"effect": "deny", "permission": "knowledge.read"}],
        ]
    )
    monkeypatch.setattr(
        "app.core.workspace_access.get_db_connection",
        connection_context(connection),
    )
    user = AuthenticatedUser(user_id=str(USER_A), workspace_id=str(WORKSPACE_A))

    with pytest.raises(HTTPException) as error:
        asyncio.run(require_workspace_permission(user, WORKSPACE_A, "knowledge.read"))

    assert error.value.status_code == 403
    assert "does not have permission" in str(error.value.detail)
    assert connection.calls[1][1] == {"membership_id": MEMBERSHIP_A}


def test_knowledge_base_list_passes_only_authorized_ids_to_database(monkeypatch) -> None:
    captured: dict[str, object] = {}
    connection = FakeConnection(
        [
            [
                {
                    "knowledge_base_id": str(KNOWLEDGE_BASE_A),
                    "display_name": "Workspace A Docs",
                    "source_type": "manual",
                    "status": "ready",
                    "version": 1,
                    "workspace_id": str(WORKSPACE_A),
                    "created_at": "2026-08-17T00:00:00Z",
                    "updated_at": "2026-08-17T00:00:00Z",
                }
            ]
        ]
    )

    async def fake_require_workspace_permission(*args, **kwargs):
        return SimpleNamespace(is_guest=True, role="viewer")

    async def fake_get_authorized_source_ids(*args, **kwargs):
        captured.update(kwargs)
        return [KNOWLEDGE_BASE_A]

    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_authorized_source_ids",
        fake_get_authorized_source_ids,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_db_connection",
        connection_context(connection),
    )

    response = asyncio.run(
        list_knowledge_bases(
            workspace_id=WORKSPACE_A,
            current_user=AuthenticatedUser(
                user_id=str(USER_A),
                is_guest=True,
                roles=["external"],
            ),
            settings=Settings(),
        )
    )

    assert isinstance(response, KnowledgeBaseListResponse)
    assert [item.knowledge_base_id for item in response.knowledge_bases] == [
        str(KNOWLEDGE_BASE_A)
    ]
    assert captured == {"is_guest": True, "workspace_role": "viewer"}
    query, params = connection.calls[0]
    assert 'AND "id" IN' in query
    assert params["workspace_id"] == WORKSPACE_A
    assert params["authorized_source_ids"] == [KNOWLEDGE_BASE_A]


def test_empty_authorized_id_list_cannot_fall_back_to_workspace_wide_results(monkeypatch) -> None:
    connection = FakeConnection([[]])

    async def fake_require_workspace_permission(*args, **kwargs):
        return SimpleNamespace(is_guest=True, role="viewer")

    async def fake_get_authorized_source_ids(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_authorized_source_ids",
        fake_get_authorized_source_ids,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_db_connection",
        connection_context(connection),
    )

    response = asyncio.run(
        list_knowledge_bases(
            workspace_id=WORKSPACE_A,
            current_user=AuthenticatedUser(user_id=str(USER_A), is_guest=True),
            settings=Settings(),
        )
    )

    assert isinstance(response, KnowledgeBaseListResponse)
    assert response.knowledge_bases == []
    query, params = connection.calls[0]
    assert 'AND "id" IN' in query
    assert params["authorized_source_ids"] == []
