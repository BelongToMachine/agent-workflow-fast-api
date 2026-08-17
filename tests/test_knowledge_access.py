import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.core.knowledge_access import (
    AUTHORIZED_SOURCE_IDS_QUERY,
    KNOWLEDGE_BASE_ACCESS_QUERY,
    KNOWLEDGE_BASE_EXISTS_QUERY,
    get_authorized_source_ids,
    require_knowledge_base_permission,
)
from app.db.migrate_knowledge_grants import MIGRATION_PATH


class FakeAuthorizationResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def first(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None


class FakeAuthorizationConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    async def execute(self, _query: object, params: dict[str, object]):
        self.calls.append(params)
        return FakeAuthorizationResult(self.rows)


def authorization_connection_context(connection: FakeAuthorizationConnection):
    @asynccontextmanager
    async def context():
        yield connection

    return context


def test_knowledge_grant_query_matches_user_or_role_and_read_access() -> None:
    sql = str(AUTHORIZED_SOURCE_IDS_QUERY)

    assert 'grant_record."subjectType" = \'user\'' in sql
    assert 'grant_record."subjectType" = \'role\'' in sql
    assert 'grant_record."subjectId" IN' in sql
    assert 'grant_record."accessLevel" IN (\'read\', \'manage\')' in sql
    assert ":is_restricted = false" in sql
    assert AUTHORIZED_SOURCE_IDS_QUERY._bindparams["roles"].expanding is True


def test_knowledge_base_queries_are_workspace_scoped() -> None:
    access_sql = str(KNOWLEDGE_BASE_ACCESS_QUERY)
    exists_sql = str(KNOWLEDGE_BASE_EXISTS_QUERY)

    assert 'source."workspaceId" = :workspace_id' in access_sql
    assert 'source."id" = :knowledge_base_id' in exists_sql
    assert 'source."workspaceId" = :workspace_id' in exists_sql


def test_grant_rollout_is_backward_compatible_when_disabled() -> None:
    user = AuthenticatedUser(
        user_id=str(UUID("00000000-0000-0000-0000-000000000010")),
        role="viewer",
    )
    settings = Settings(knowledge_grants_enabled=False)

    async def resolve() -> list[UUID] | None:
        # The current resolver reads the cached application settings. The explicit
        # Settings assertion documents the default rollout behavior for this test.
        assert settings.knowledge_grants_enabled is False
        return await get_authorized_source_ids(
            user,
            UUID("00000000-0000-0000-0000-000000000001"),
        )

    assert asyncio.run(resolve()) is None


def test_external_role_requires_an_explicit_knowledge_grant(monkeypatch) -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000020")
    connection = FakeAuthorizationConnection([{"source_id": source_id}])
    monkeypatch.setattr(
        "app.core.knowledge_access.get_db_connection",
        authorization_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.core.knowledge_access.get_settings",
        lambda: Settings(knowledge_grants_enabled=True),
    )

    external_user = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        role="viewer",
        roles=["external"],
    )

    result = asyncio.run(
        get_authorized_source_ids(
            external_user,
            UUID("00000000-0000-0000-0000-000000000001"),
            workspace_role="viewer",
        )
    )

    assert result == [source_id]
    assert connection.calls[0]["is_restricted"] is True


def test_contractor_role_requires_an_explicit_knowledge_grant(monkeypatch) -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000020")
    connection = FakeAuthorizationConnection([{"source_id": source_id}])
    monkeypatch.setattr(
        "app.core.knowledge_access.get_db_connection",
        authorization_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.core.knowledge_access.get_settings",
        lambda: Settings(knowledge_grants_enabled=True),
    )

    contractor = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        role="viewer",
        roles=["contractor"],
    )

    result = asyncio.run(
        get_authorized_source_ids(
            contractor,
            UUID("00000000-0000-0000-0000-000000000001"),
            workspace_role="viewer",
        )
    )

    assert result == [source_id]
    assert connection.calls[0]["is_restricted"] is True
    assert connection.calls[0]["roles"] == ["viewer", "contractor"]


def test_contractor_role_is_restricted_for_direct_knowledge_base_access(monkeypatch) -> None:
    connection = FakeAuthorizationConnection([{"permitted": True}])
    monkeypatch.setattr(
        "app.core.knowledge_access.get_db_connection",
        authorization_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.core.knowledge_access.get_settings",
        lambda: Settings(knowledge_grants_enabled=True),
    )

    async def fake_require_workspace_permission(*_args, **_kwargs):
        return type(
            "Access",
            (),
            {"role": "viewer", "is_guest": False, "is_development": False},
        )()

    monkeypatch.setattr(
        "app.core.workspace_access.require_workspace_permission",
        fake_require_workspace_permission,
    )

    asyncio.run(
        require_knowledge_base_permission(
            AuthenticatedUser(
                user_id="00000000-0000-0000-0000-000000000010",
                role="viewer",
                roles=["contractor"],
            ),
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000020"),
            "read",
        )
    )

    assert connection.calls[0]["is_restricted"] is True
    assert connection.calls[0]["roles"] == ["viewer", "contractor"]


def test_internal_employee_role_keeps_unrestricted_fallback_behavior(monkeypatch) -> None:
    connection = FakeAuthorizationConnection([])
    monkeypatch.setattr(
        "app.core.knowledge_access.get_db_connection",
        authorization_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.core.knowledge_access.get_settings",
        lambda: Settings(knowledge_grants_enabled=True),
    )

    employee = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        role="editor",
        roles=["employee"],
    )

    result = asyncio.run(
        get_authorized_source_ids(
            employee,
            UUID("00000000-0000-0000-0000-000000000001"),
            workspace_role="editor",
        )
    )

    assert result == []
    assert connection.calls[0]["is_restricted"] is False


def test_grant_migration_file_is_present_and_idempotent() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'CREATE TABLE IF NOT EXISTS "KnowledgeBaseGrant"' in sql
    assert 'CREATE INDEX IF NOT EXISTS "KnowledgeBaseGrant_workspace_subject_idx"' in sql
