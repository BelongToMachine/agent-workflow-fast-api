import asyncio
import io
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.api.routes.knowledge_files import (
    FILE_INSERT_QUERY,
    FILE_LIST_QUERY,
    KnowledgeFileSummary,
    _chunk_text,
    _content_matches_extension,
    _extract_text,
    _safe_filename,
    _storage_path,
    process_knowledge_file,
    upload_knowledge_file,
)
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.db.migrate_knowledge_ingestion import MIGRATION_PATH
from app.main import app
from app.services.storage import LocalKnowledgeStorage

client = TestClient(app)


class FakeResult:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None


class FakeIngestionConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.status_updates: list[dict[str, object]] = []
        self.inserted_chunks: list[dict[str, object]] = []

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        if sql.lstrip().startswith("SELECT"):
            return FakeResult(self.row)
        if 'UPDATE "KnowledgeFile"' in sql:
            self.status_updates.append(parameters or {})
        if 'INSERT INTO "KnowledgeChunk"' in sql:
            self.inserted_chunks.extend(parameters or [])
        return FakeResult()

    def begin(self):
        return FakeTransaction()


class FakeConnectionContext:
    def __init__(self, connection: FakeIngestionConnection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args) -> None:
        return None


class FakeUploadResult:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        scalar_value: object | None = None,
    ) -> None:
        self.row = row
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def one(self) -> dict[str, object]:
        assert self.row is not None
        return self.row

    def scalar_one_or_none(self) -> object | None:
        return self.scalar_value


class FakeUploadConnection:
    def __init__(self, *, inserted: bool = True) -> None:
        self.inserted = inserted
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.file_row: dict[str, object] = {
            "byte_size": 0,
            "created_at": datetime(2026, 8, 17, 12, 30),
            "error_message": None,
            "file_hash": "",
            "file_id": None,
            "knowledge_base_id": UUID("00000000-0000-0000-0000-000000000002"),
            "mime_type": "text/csv",
            "original_name": "data.csv",
            "status": "pending",
            "storage_provider": "local",
            "updated_at": datetime(2026, 8, 17, 12, 30),
            "workspace_id": UUID("00000000-0000-0000-0000-000000000001"),
        }

    async def execute(self, query: object, params: dict[str, object]) -> FakeUploadResult:
        sql = str(query)
        self.calls.append((sql, params))
        if "INSERT INTO \"KnowledgeFile\"" in sql:
            if self.inserted:
                self.file_row.update(
                    {
                        "byte_size": params["byte_size"],
                        "file_hash": params["file_hash"],
                        "file_id": params["file_id"],
                        "original_name": params["original_name"],
                        "storage_provider": params["storage_provider"],
                        "workspace_id": params["workspace_id"],
                    }
                )
                return FakeUploadResult(scalar_value=params["file_id"])
            return FakeUploadResult(scalar_value=None)
        if "SELECT" in sql:
            return FakeUploadResult(row=self.file_row)
        return FakeUploadResult()

    def begin(self) -> FakeTransaction:
        return FakeTransaction()


def upload_connection_context(connection: FakeUploadConnection):
    @asynccontextmanager
    async def context():
        yield connection

    return context


class FakeUploadStorage:
    provider = "local"

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes]] = []
        self.deleted: list[str] = []

    async def put(self, storage_key: str, content: bytes) -> None:
        self.uploads.append((storage_key, content))

    async def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)


class FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks: list[tuple[object, tuple[object, ...]]] = []

    def add_task(self, function, *args, **_kwargs) -> None:
        self.tasks.append((function, args))


@pytest.fixture
def ingestion_disabled_settings():
    settings = Settings(
        environment="development",
        auth_secret="code-secret",
        knowledge_ingestion_enabled=False,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def test_knowledge_file_summary_requires_storage_metadata() -> None:
    with pytest.raises(ValidationError):
        KnowledgeFileSummary.model_validate(
            {
                "byteSize": 10,
                "createdAt": "2026-08-17T00:00:00Z",
                "fileHash": "abc",
                "fileId": str(UUID(int=1)),
                "knowledgeBaseId": str(UUID(int=2)),
                "mimeType": "text/csv",
                "originalName": "data.csv",
                "status": "pending",
                "updatedAt": "2026-08-17T00:00:00Z",
                "workspaceId": str(UUID(int=3)),
            }
        )


def test_file_parser_supports_csv_and_xlsx() -> None:
    assert "name\tprice" in _extract_text("data.csv", b"name,price\nchair,10")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["name", "price"])
    sheet.append(["chair", 10])
    output = io.BytesIO()
    workbook.save(output)

    extracted = _extract_text("data.xlsx", output.getvalue())
    assert "[Sheet: Products]" in extracted
    assert "chair\t10" in extracted


def test_binary_file_signatures_match_the_declared_extension() -> None:
    assert _content_matches_extension(".pdf", b"%PDF-1.7 content")
    assert _content_matches_extension(".xlsx", b"PK\x03\x04workbook")
    assert not _content_matches_extension(".pdf", b"not-a-pdf")
    assert not _content_matches_extension(".xlsx", b"not-a-workbook")
    assert _content_matches_extension(".csv", b"name,price\nchair,10")


def test_file_name_and_storage_path_are_sandboxed(tmp_path) -> None:
    assert _safe_filename("../../secret file.csv") == "secret_file.csv"
    settings = Settings(knowledge_storage_dir=str(tmp_path))

    with pytest.raises(Exception):
        _storage_path(settings, "../../secret.txt")


def test_chunking_adds_overlap_without_empty_chunks() -> None:
    chunks = _chunk_text("a" * 2500)

    assert len(chunks) == 3
    assert all(chunks)
    assert chunks[0][-120:] == chunks[1][:120]


def test_process_knowledge_file_reads_chunks_and_marks_file_ready(monkeypatch, tmp_path) -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000010")
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    knowledge_base_id = UUID("00000000-0000-0000-0000-000000000002")
    storage_key = "workspace/knowledge/data.csv"
    row = {
        "storage_provider": "local",
        "storage_key": storage_key,
        "original_name": "data.csv",
        "knowledge_base_id": knowledge_base_id,
    }
    settings = Settings(
        knowledge_ingestion_enabled=True,
        knowledge_embeddings_enabled=False,
        knowledge_storage_dir=str(tmp_path),
    )
    storage = LocalKnowledgeStorage(str(tmp_path))
    connection = FakeIngestionConnection(row)

    asyncio.run(storage.put(storage_key, b"name,price\nchair,10"))
    monkeypatch.setattr("app.api.routes.knowledge_files.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.routes.knowledge_files.get_knowledge_storage_for_provider",
        lambda _settings, _provider: storage,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_files.get_db_connection",
        lambda: FakeConnectionContext(connection),
    )

    asyncio.run(process_knowledge_file(file_id, workspace_id))

    assert [update["status"] for update in connection.status_updates] == [
        "processing",
        "ready",
    ]
    assert [chunk["content"] for chunk in connection.inserted_chunks] == [
        "name\tprice\nchair\t10"
    ]
    assert connection.inserted_chunks[0]["knowledge_base_id"] == knowledge_base_id


def test_ingestion_migration_is_idempotent_and_contains_chunk_table() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'CREATE TABLE IF NOT EXISTS "KnowledgeFile"' in sql
    assert 'CREATE TABLE IF NOT EXISTS "KnowledgeChunk"' in sql
    assert '"workspaceId" = :workspace_id' in str(FILE_LIST_QUERY)
    assert ":storage_provider" in str(FILE_INSERT_QUERY)


def test_upload_is_gated_until_ingestion_migration_is_applied(
    ingestion_disabled_settings: Settings,
) -> None:
    response = client.post(
        "/api/v1/knowledge-bases/00000000-0000-0000-0000-000000000002/files",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        files={"file": ("data.csv", b"name,price\nchair,10", "text/csv")},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "knowledge_ingestion:disabled"


def test_upload_route_persists_workspace_scoped_file_and_schedules_processing(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    knowledge_base_id = UUID("00000000-0000-0000-0000-000000000002")
    user_id = UUID("00000000-0000-0000-0000-000000000010")
    settings = Settings(
        knowledge_ingestion_enabled=True,
        knowledge_storage_dir="storage/knowledge",
    )
    connection = FakeUploadConnection()
    storage = FakeUploadStorage()
    background_tasks = FakeBackgroundTasks()
    permission: dict[str, object] = {}

    async def fake_require_permission(
        _current_user,
        requested_workspace_id,
        requested_knowledge_base_id,
        requested_permission,
    ):
        permission.update(
            {
                "workspace_id": requested_workspace_id,
                "knowledge_base_id": requested_knowledge_base_id,
                "permission": requested_permission,
            }
        )

    monkeypatch.setattr(
        "app.api.routes.knowledge_files.require_knowledge_base_permission",
        fake_require_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_files.get_knowledge_storage",
        lambda _settings: storage,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_files.get_db_connection",
        upload_connection_context(connection),
    )

    result = asyncio.run(
        upload_knowledge_file(
            knowledge_base_id=knowledge_base_id,
            background_tasks=background_tasks,
            file=UploadFile(
                file=io.BytesIO(b"name,price\nchair,10"),
                filename="../data.csv",
                headers=Headers({"content-type": "text/csv"}),
            ),
            workspace_id=workspace_id,
            current_user=AuthenticatedUser(user_id=str(user_id)),
            settings=settings,
        )
    )

    assert result["file"].workspace_id == str(workspace_id)
    assert result["file"].knowledge_base_id == str(knowledge_base_id)
    assert permission == {
        "workspace_id": workspace_id,
        "knowledge_base_id": knowledge_base_id,
        "permission": "manage",
    }
    assert len(storage.uploads) == 1
    storage_key, stored_content = storage.uploads[0]
    assert storage_key.startswith(f"{workspace_id}/{knowledge_base_id}/")
    assert storage_key.endswith("-data.csv")
    assert stored_content == b"name,price\nchair,10"
    assert connection.calls[0][1]["workspace_id"] == workspace_id
    assert connection.calls[1][1]["workspace_id"] == workspace_id
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0][0] is process_knowledge_file
    assert background_tasks.tasks[0][1] == (
        connection.file_row["file_id"],
        workspace_id,
    )


def test_duplicate_upload_removes_object_after_database_conflict(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    knowledge_base_id = UUID("00000000-0000-0000-0000-000000000002")
    settings = Settings(knowledge_ingestion_enabled=True)
    connection = FakeUploadConnection(inserted=False)
    storage = FakeUploadStorage()

    async def fake_require_permission(*_args, **_kwargs):
        return SimpleNamespace(role="owner")

    monkeypatch.setattr(
        "app.api.routes.knowledge_files.require_knowledge_base_permission",
        fake_require_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_files.get_knowledge_storage",
        lambda _settings: storage,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_files.get_db_connection",
        upload_connection_context(connection),
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            upload_knowledge_file(
                knowledge_base_id=knowledge_base_id,
                background_tasks=FakeBackgroundTasks(),
                file=UploadFile(
                    file=io.BytesIO(b"name,price\nchair,10"),
                    filename="data.csv",
                    headers=Headers({"content-type": "text/csv"}),
                ),
                workspace_id=workspace_id,
                current_user=AuthenticatedUser(
                    user_id="00000000-0000-0000-0000-000000000010"
                ),
                settings=settings,
            )
        )

    assert getattr(error.value, "status_code", None) == 409
    assert len(storage.uploads) == 1
    assert storage.deleted == [storage.uploads[0][0]]
