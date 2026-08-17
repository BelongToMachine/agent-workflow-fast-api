import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.routes.knowledge_search import SEARCH_QUERY, KnowledgeSearchRequest
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app
from app.services.agent_tools import (
    AgentToolError,
    KnowledgeBaseToolInput,
    agent_tool_definitions,
    execute_agent_tool,
)

client = TestClient(app)


def test_knowledge_search_request_validates_limit() -> None:
    assert KnowledgeSearchRequest(query="pricing", limit=5).limit == 5


def test_agent_tools_expose_only_read_only_enterprise_search_tools() -> None:
    definitions = agent_tool_definitions()

    assert [item["function"]["name"] for item in definitions] == [
        "searchProductsTool",
        "searchContentTool",
        "searchKnowledgeBaseTool",
    ]
    assert all(item["function"]["parameters"]["type"] == "object" for item in definitions)


def test_disabled_knowledge_embeddings_do_not_expose_knowledge_base_tool() -> None:
    definitions = agent_tool_definitions(include_knowledge_base=False)

    assert [item["function"]["name"] for item in definitions] == [
        "searchProductsTool",
        "searchContentTool",
    ]


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


def test_knowledge_base_tool_requires_a_valid_knowledge_base_id() -> None:
    with pytest.raises(ValueError):
        KnowledgeBaseToolInput.model_validate(
            {"knowledgeBaseId": "not-a-uuid", "query": "pricing"}
        )


def test_knowledge_base_tool_calls_permission_checked_search(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_search_knowledge_base(**kwargs):
        captured.update(kwargs)
        return KnowledgeSearchRequest.model_validate({"query": "pricing", "limit": 3})

    monkeypatch.setattr(
        "app.services.agent_tools.search_knowledge_base",
        fake_search_knowledge_base,
    )

    result = asyncio.run(
        execute_agent_tool(
            "searchKnowledgeBaseTool",
            {
                "knowledgeBaseId": "00000000-0000-0000-0000-000000000002",
                "limit": 3,
                "query": "pricing",
            },
            current_user=AuthenticatedUser(user_id="development-user", is_development=True),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
        )
    )

    assert result == {"query": "pricing", "limit": 3}
    assert captured["knowledge_base_id"] == UUID(
        "00000000-0000-0000-0000-000000000002"
    )
    assert captured["workspace_id"] == UUID("00000000-0000-0000-0000-000000000001")


def test_knowledge_base_tool_cannot_bypass_chat_knowledge_permission() -> None:
    with pytest.raises(AgentToolError, match="not allowed"):
        asyncio.run(
            execute_agent_tool(
                "searchKnowledgeBaseTool",
                {
                    "knowledgeBaseId": "00000000-0000-0000-0000-000000000002",
                    "query": "pricing",
                },
                current_user=AuthenticatedUser(user_id="development-user"),
                workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
                can_query_knowledge=False,
            )
        )
