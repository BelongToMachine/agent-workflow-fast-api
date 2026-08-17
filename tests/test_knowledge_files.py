import io
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import ValidationError

from app.api.routes.knowledge_files import (
    FILE_INSERT_QUERY,
    FILE_LIST_QUERY,
    KnowledgeFileSummary,
    _chunk_text,
    _extract_text,
    _safe_filename,
    _storage_path,
)
from app.core.config import Settings, get_settings
from app.db.migrate_knowledge_ingestion import MIGRATION_PATH
from app.main import app

client = TestClient(app)


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
