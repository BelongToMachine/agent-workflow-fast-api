from fastapi.testclient import TestClient

from app.api.routes.knowledge_search import SEARCH_QUERY, KnowledgeSearchRequest
from app.core.config import Settings, get_settings
from app.main import app
from app.services.agent_tools import agent_tool_definitions

client = TestClient(app)


def test_knowledge_search_request_validates_limit() -> None:
    assert KnowledgeSearchRequest(query="pricing", limit=5).limit == 5


def test_agent_tools_expose_only_read_only_enterprise_search_tools() -> None:
    definitions = agent_tool_definitions()

    assert [item["function"]["name"] for item in definitions] == [
        "searchProductsTool",
        "searchContentTool",
    ]
    assert all(item["function"]["parameters"]["type"] == "object" for item in definitions)


def test_knowledge_search_query_filters_workspace_and_knowledge_base() -> None:
    sql = str(SEARCH_QUERY)

    assert 'chunk."workspaceId" = :workspace_id' in sql
    assert 'chunk."knowledgeBaseId" = :knowledge_base_id' in sql
    assert 'chunk."embedding" <=> CAST(:embedding AS vector)' in sql


def test_knowledge_search_is_disabled_by_default() -> None:
    settings = Settings(environment="development", knowledge_embeddings_enabled=False)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.post(
            "/api/v1/knowledge-bases/00000000-0000-0000-0000-000000000002/search",
            params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
            json={"query": "pricing"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 409
    assert response.json()["code"] == "knowledge_search:disabled"
