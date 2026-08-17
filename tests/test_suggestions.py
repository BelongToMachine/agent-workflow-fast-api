from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.suggestions import (
    DOCUMENT_ACCESS_QUERY,
    SUGGESTIONS_QUERY,
    SuggestionRecord,
    _suggestion_record,
)
from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


def test_suggestion_record_matches_existing_camel_case_shape() -> None:
    record = _suggestion_record(
        {
            "created_at": datetime(2026, 8, 17, 12, 31),
            "description": "Improve clarity",
            "document_created_at": datetime(2026, 8, 17, 12, 30),
            "document_id": UUID("00000000-0000-0000-0000-000000000010"),
            "id": UUID("00000000-0000-0000-0000-000000000011"),
            "is_resolved": False,
            "original_text": "old text",
            "suggested_text": "new text",
            "user_id": UUID("00000000-0000-0000-0000-000000000012"),
        }
    )

    assert record.model_dump(by_alias=True) == {
        "createdAt": "2026-08-17T12:31:00.000Z",
        "description": "Improve clarity",
        "documentCreatedAt": "2026-08-17T12:30:00.000Z",
        "documentId": "00000000-0000-0000-0000-000000000010",
        "id": "00000000-0000-0000-0000-000000000011",
        "isResolved": False,
        "originalText": "old text",
        "suggestedText": "new text",
        "userId": "00000000-0000-0000-0000-000000000012",
    }


def test_suggestion_record_requires_document_identity() -> None:
    with pytest.raises(ValidationError):
        SuggestionRecord.model_validate(
            {
                "createdAt": "2026-08-17T12:31:00.000Z",
                "description": None,
                "documentCreatedAt": "2026-08-17T12:30:00.000Z",
                "id": "00000000-0000-0000-0000-000000000011",
                "isResolved": False,
                "originalText": "old text",
                "suggestedText": "new text",
                "userId": "00000000-0000-0000-0000-000000000012",
            }
        )


def test_suggestion_queries_scope_document_to_workspace_and_owner() -> None:
    document_query = str(DOCUMENT_ACCESS_QUERY)
    suggestions_query = str(SUGGESTIONS_QUERY)

    assert 'WHERE "id" = :document_id' in document_query
    assert '"userId" AS user_id' in document_query
    assert '"workspaceId" AS workspace_id' in document_query
    assert 'WHERE "documentId" = :document_id' in suggestions_query


def test_suggestions_require_authentication() -> None:
    settings = Settings(environment="development", auth_required=True)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.get(
            "/api/v1/suggestions",
            params={
                "documentId": "00000000-0000-0000-0000-000000000010",
                "workspace_id": "00000000-0000-0000-0000-000000000001",
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 401
