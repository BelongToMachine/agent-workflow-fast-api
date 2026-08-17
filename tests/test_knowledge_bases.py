import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes.knowledge_bases import (
    KNOWLEDGE_BASE_DELETE,
    KNOWLEDGE_BASE_SELECT,
    KnowledgeBaseSummary,
    KnowledgeBaseWriteRequest,
    _cleanup_knowledge_base_files,
    create_knowledge_base,
    delete_knowledge_base,
    knowledge_base_select_query,
    update_knowledge_base,
)
from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.main import app
from app.services.storage import StorageError

client = TestClient(app)

WORKSPACE_A = UUID("00000000-0000-0000-0000-000000000001")
KNOWLEDGE_BASE_A = UUID("00000000-0000-0000-0000-000000000002")
USER_A = UUID("00000000-0000-0000-0000-000000000010")


class FakeResult:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        scalar_value: object | None = None,
    ) -> None:
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def first(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self) -> object | None:
        return self.scalar_value


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None


class FakeKnowledgeBaseConnection:
    def __init__(
        self,
        *,
        knowledge_base_row: dict[str, object] | None = None,
        update_result: object | None = None,
        file_rows: list[dict[str, object]] | None = None,
        delete_row: dict[str, object] | None = None,
    ) -> None:
        self.knowledge_base_row = knowledge_base_row
        self.update_result = update_result
        self.file_rows = file_rows or []
        self.delete_row = delete_row
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, query: object, params: dict[str, object]) -> FakeResult:
        sql = str(query)
        self.calls.append((sql, params))
        if '"KnowledgeBase"' in sql and sql.lstrip().startswith("SELECT"):
            return FakeResult([self.knowledge_base_row] if self.knowledge_base_row else [])
        if '"KnowledgeBase"' in sql and sql.lstrip().startswith("INSERT"):
            if self.knowledge_base_row is not None:
                self.knowledge_base_row["knowledge_base_id"] = params["knowledge_base_id"]
                self.knowledge_base_row["workspace_id"] = params["workspace_id"]
            return FakeResult()
        if '"KnowledgeBase"' in sql and sql.lstrip().startswith("UPDATE"):
            return FakeResult(scalar_value=self.update_result)
        if '"KnowledgeFile"' in sql and sql.lstrip().startswith("SELECT"):
            return FakeResult(self.file_rows)
        if sql.lstrip().startswith("DELETE"):
            return FakeResult([self.delete_row] if self.delete_row else [])
        return FakeResult()

    def begin(self) -> FakeTransaction:
        return FakeTransaction()


def connection_context(connection: FakeKnowledgeBaseConnection):
    @asynccontextmanager
    async def context():
        yield connection

    return context


def knowledge_base_row(name: str = "Sales Docs") -> dict[str, object]:
    timestamp = datetime(2026, 8, 17, 12, 30)
    return {
        "knowledge_base_id": KNOWLEDGE_BASE_A,
        "display_name": name,
        "source_type": "manual",
        "status": "ready",
        "version": 1,
        "workspace_id": WORKSPACE_A,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def persisted_user() -> AuthenticatedUser:
    return AuthenticatedUser(user_id=str(USER_A), role="owner")


def test_knowledge_base_name_is_normalized() -> None:
    payload = KnowledgeBaseWriteRequest.model_validate(
        {"displayName": "  Sales Docs  ", "sourceType": " manual "}
    )

    assert payload.display_name == "Sales Docs"
    assert payload.source_type == "manual"


def test_knowledge_base_query_is_workspace_scoped() -> None:
    assert '"workspaceId" = :workspace_id' in str(KNOWLEDGE_BASE_SELECT)
    assert '"workspaceId" = :workspace_id' in str(KNOWLEDGE_BASE_DELETE)


def test_knowledge_base_list_query_can_apply_authorized_source_ids() -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000002")
    query = knowledge_base_select_query(authorized_source_ids=[source_id])

    assert 'AND "id" IN' in str(query)
    assert "authorized_source_ids" in str(query)
    assert query._bindparams["authorized_source_ids"].expanding is True


def test_knowledge_base_creation_requires_a_persisted_identity() -> None:
    response = client.post(
        "/api/v1/knowledge-bases",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        json={"displayName": "Sales Docs", "sourceType": "manual"},
    )

    assert response.status_code == 401


def test_knowledge_base_deletion_requires_a_persisted_identity() -> None:
    response = client.delete(
        "/api/v1/knowledge-bases/00000000-0000-0000-0000-000000000002",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401


def test_knowledge_base_storage_cleanup_is_best_effort(monkeypatch) -> None:
    class FakeStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def delete(self, storage_key: str) -> None:
            if storage_key == "broken.pdf":
                raise StorageError("storage unavailable")
            self.deleted.append(storage_key)

    storage = FakeStorage()
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_knowledge_storage_for_provider",
        lambda _settings, _provider: storage,
    )

    failed_count = asyncio.run(
        _cleanup_knowledge_base_files(
            Settings(),
            [
                {"storage_key": "kept.pdf", "storage_provider": "local"},
                {"storage_key": "broken.pdf", "storage_provider": "local"},
            ],
        )
    )

    assert storage.deleted == ["kept.pdf"]
    assert failed_count == 1


def test_knowledge_base_create_and_update_routes_keep_workspace_and_audit_scope(
    monkeypatch,
) -> None:
    connection = FakeKnowledgeBaseConnection(
        knowledge_base_row=knowledge_base_row(),
        update_result=KNOWLEDGE_BASE_A,
    )
    settings = Settings(knowledge_base_entity_enabled=True)

    async def fake_require_workspace_permission(*_args, **_kwargs):
        return SimpleNamespace(role="owner", permissions=["knowledge.manage"])

    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_db_connection",
        connection_context(connection),
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases._write_audit_log",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    created = asyncio.run(
        create_knowledge_base(
            KnowledgeBaseWriteRequest(displayName="Sales Docs", sourceType="manual"),
            workspace_id=WORKSPACE_A,
            current_user=persisted_user(),
            settings=settings,
        )
    )
    connection.knowledge_base_row = knowledge_base_row("Updated Sales")
    updated = asyncio.run(
        update_knowledge_base(
            KNOWLEDGE_BASE_A,
            KnowledgeBaseWriteRequest(displayName="Updated Sales", sourceType="manual"),
            workspace_id=WORKSPACE_A,
            current_user=persisted_user(),
            settings=settings,
        )
    )

    assert isinstance(created, KnowledgeBaseSummary)
    assert isinstance(updated, KnowledgeBaseSummary)
    assert created.workspace_id == str(WORKSPACE_A)
    assert updated.workspace_id == str(WORKSPACE_A)
    assert all(
        params.get("workspace_id") == WORKSPACE_A
        for _sql, params in connection.calls
        if "workspace_id" in params
    )
    assert sum("INSERT INTO \"KnowledgeBase\"" in sql for sql, _ in connection.calls) == 1
    assert sum("UPDATE \"KnowledgeBase\"" in sql for sql, _ in connection.calls) == 1


def test_knowledge_base_delete_route_cascades_and_cleans_storage(monkeypatch) -> None:
    storage = SimpleNamespace(deleted=[])

    async def delete(storage_key: str) -> None:
        storage.deleted.append(storage_key)

    storage.delete = delete
    connection = FakeKnowledgeBaseConnection(
        file_rows=[
            {"storage_key": "sales.pdf", "storage_provider": "local"},
            {"storage_key": "catalog.csv", "storage_provider": "local"},
        ],
        delete_row={"id": KNOWLEDGE_BASE_A},
    )
    settings = Settings(
        knowledge_base_entity_enabled=True,
        knowledge_ingestion_enabled=True,
    )

    async def fake_require_knowledge_base_permission(*_args, **_kwargs):
        return SimpleNamespace(role="owner")

    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.require_knowledge_base_permission",
        fake_require_knowledge_base_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_db_connection",
        connection_context(connection),
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_knowledge_storage_for_provider",
        lambda _settings, _provider: storage,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases._write_audit_log",
        lambda *args, **kwargs: asyncio.sleep(0),
    )

    result = asyncio.run(
        delete_knowledge_base(
            KNOWLEDGE_BASE_A,
            workspace_id=WORKSPACE_A,
            current_user=persisted_user(),
            settings=settings,
        )
    )

    assert result == {
        "deleted": True,
        "storageCleanup": "completed",
    }
    assert storage.deleted == ["sales.pdf", "catalog.csv"]
    assert any(sql.lstrip().startswith("DELETE") for sql, _ in connection.calls)
    assert all(
        params.get("workspace_id") == WORKSPACE_A
        for _sql, params in connection.calls
        if "workspace_id" in params
    )
