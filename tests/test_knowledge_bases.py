from fastapi.testclient import TestClient

from app.api.routes.knowledge_bases import (
    KNOWLEDGE_BASE_SELECT,
    KnowledgeBaseWriteRequest,
)
from app.main import app

client = TestClient(app)


def test_knowledge_base_name_is_normalized() -> None:
    payload = KnowledgeBaseWriteRequest.model_validate(
        {"displayName": "  Sales Docs  ", "sourceType": " manual "}
    )

    assert payload.display_name == "Sales Docs"
    assert payload.source_type == "manual"


def test_knowledge_base_query_is_workspace_scoped() -> None:
    assert '"workspaceId" = :workspace_id' in str(KNOWLEDGE_BASE_SELECT)


def test_knowledge_base_creation_requires_a_persisted_identity() -> None:
    response = client.post(
        "/api/v1/knowledge-bases",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        json={"displayName": "Sales Docs", "sourceType": "manual"},
    )

    assert response.status_code == 401
