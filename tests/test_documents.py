from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.documents import (
    DELETE_DOCUMENTS_QUERY,
    DOCUMENTS_BY_ID_QUERY,
    DocumentRecord,
    DocumentWriteRequest,
    _document_record,
    _parse_timestamp,
)
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


def test_document_record_matches_nextjs_camel_case_shape() -> None:
    record = _document_record(
        {
            "content": "draft",
            "created_at": datetime(2026, 8, 17, 12, 30),
            "id": UUID("00000000-0000-0000-0000-000000000010"),
            "kind": "text",
            "title": "Brief",
            "user_id": UUID("00000000-0000-0000-0000-000000000011"),
            "workspace_id": UUID("00000000-0000-0000-0000-000000000012"),
        }
    )

    assert record.model_dump(by_alias=True) == {
        "content": "draft",
        "createdAt": "2026-08-17T12:30:00.000Z",
        "id": "00000000-0000-0000-0000-000000000010",
        "kind": "text",
        "title": "Brief",
        "userId": "00000000-0000-0000-0000-000000000011",
        "workspaceId": "00000000-0000-0000-0000-000000000012",
    }


def test_document_write_request_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        DocumentWriteRequest.model_validate(
            {
                "content": "draft",
                "kind": "spreadsheet",
                "title": "Brief",
            }
        )


def test_document_queries_scope_by_user_and_workspace() -> None:
    query = str(DOCUMENTS_BY_ID_QUERY)
    delete_query = str(DELETE_DOCUMENTS_QUERY)

    assert '"userId" = :user_id' in query
    assert '"workspaceId" = :workspace_id' in query
    assert '"userId" = :user_id' in delete_query
    assert '"workspaceId" = :workspace_id' in delete_query


def test_timestamp_parser_accepts_iso_utc_and_rejects_invalid() -> None:
    parsed = _parse_timestamp("2026-08-17T12:30:00Z")
    assert parsed.tzinfo is not None
    assert parsed.isoformat() == "2026-08-17T12:30:00+00:00"

    with pytest.raises(Exception):
        _parse_timestamp("not-a-timestamp")


def test_document_endpoint_rejects_anonymous_development_identity(
    development_settings: Settings,
) -> None:
    response = client.get(
        "/api/v1/documents",
        params={
            "id": "00000000-0000-0000-0000-000000000010",
            "workspace_id": "00000000-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 401


def test_document_record_requires_workspace_id() -> None:
    with pytest.raises(ValidationError):
        DocumentRecord.model_validate(
            {
                "content": "draft",
                "createdAt": "2026-08-17T12:30:00.000Z",
                "id": "00000000-0000-0000-0000-000000000010",
                "kind": "text",
                "title": "Brief",
                "userId": "00000000-0000-0000-0000-000000000011",
            }
        )
