from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes.content import (
    ContentSearchRequest,
    _build_content_search_query,
    _iso_timestamp,
)
from app.main import app

client = TestClient(app)


def test_content_search_requires_a_json_body() -> None:
    response = client.post("/api/v1/content/search")

    assert response.status_code == 422


def test_content_search_accepts_nextjs_camel_case_request_fields() -> None:
    payload = ContentSearchRequest.model_validate(
        {
            "workspaceId": "00000000-0000-0000-0000-000000000001",
            "recordType": "shoot_plan",
            "sourceFileNames": ["content.xlsx"],
        }
    )

    assert payload.workspace_id == UUID("00000000-0000-0000-0000-000000000001")
    assert payload.record_type == "shoot_plan"
    assert payload.source_file_names == ["content.xlsx"]


def test_content_search_rejects_unknown_record_type() -> None:
    response = client.post(
        "/api/v1/content/search",
        json={
            "workspaceId": "00000000-0000-0000-0000-000000000001",
            "recordType": "unknown",
        },
    )

    assert response.status_code == 422


def test_content_query_contains_nextjs_filters() -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000002")
    query, params = _build_content_search_query(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        account="official",
        language="zh",
        product="charger",
        query="launch",
        record_type="copy",
        status="approved",
        submitter="Alice",
        source_ids=[source_id],
        limit=20,
    )

    sql = str(query)
    assert 'source."workspaceId" = :workspace_id' in sql
    assert 'record."sourceId" IN' in sql
    assert 'record."searchText" ILIKE :query_pattern' in sql
    assert params["record_type"] == "copy"
    assert params["source_ids"] == [source_id]
    assert params["limit"] == 20


def test_content_timestamp_matches_nextjs_iso_format() -> None:
    assert _iso_timestamp(datetime(2026, 6, 8, 15, 59, 17)) == ("2026-06-08T15:59:17.000Z")
