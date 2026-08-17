import asyncio
from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes.knowledge_sources import (
    _build_knowledge_sources_query,
    _iso_timestamp,
)
from app.core.auth import AuthenticatedUser
from app.core.workspace_access import require_workspace_permission
from app.main import app

client = TestClient(app)


def test_knowledge_sources_requires_workspace_context() -> None:
    response = client.get("/api/v1/knowledge-sources")

    assert response.status_code == 422


def test_development_user_can_use_the_local_knowledge_boundary() -> None:
    user = AuthenticatedUser(user_id="development-user", is_development=True)
    access = asyncio.run(
        require_workspace_permission(
            user,
            UUID("00000000-0000-0000-0000-000000000001"),
            "knowledge.read",
        )
    )

    assert access.role == "owner"
    assert "knowledge.read" in access.permissions
    assert access.is_development is True


def test_knowledge_source_timestamps_are_iso_8601_utc() -> None:
    assert _iso_timestamp(datetime(2026, 6, 8, 15, 59, 17)) == ("2026-06-08T15:59:17.000Z")


def test_knowledge_source_query_can_apply_knowledge_base_grants() -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    source_id = UUID("00000000-0000-0000-0000-000000000002")
    query, params = _build_knowledge_sources_query(workspace_id, [source_id])

    assert 'source."id" IN' in str(query)
    assert params["workspace_id"] == str(workspace_id)
    assert params["authorized_source_ids"] == [source_id]
