import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.routes.knowledge_bases import KnowledgeBaseListResponse
from app.api.routes.knowledge_files import KnowledgeFileListResponse
from app.api.routes.knowledge_search import (
    SEARCH_QUERY,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    search_knowledge_base,
)
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app
from app.services.agent_tools import (
    AgentToolError,
    KnowledgeBaseLookupToolInput,
    KnowledgeBaseToolInput,
    KnowledgeFileListToolInput,
    KnowledgeFileLookupToolInput,
    agent_tool_definitions,
    execute_agent_tool,
)

client = TestClient(app)

WORKSPACE_A = UUID("00000000-0000-0000-0000-000000000001")
KNOWLEDGE_BASE_A = UUID("00000000-0000-0000-0000-000000000002")
FILE_A = UUID("00000000-0000-0000-0000-000000000003")
CHUNK_A = UUID("00000000-0000-0000-0000-000000000004")


class FakeSearchResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows


class FakeSearchConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, query: object, params: dict[str, object]) -> FakeSearchResult:
        self.calls.append((str(query), params))
        return FakeSearchResult(self.rows)


def search_connection_context(connection: FakeSearchConnection):
    @asynccontextmanager
    async def context():
        yield connection

    return context


def test_knowledge_search_request_validates_limit() -> None:
    assert KnowledgeSearchRequest(query="pricing", limit=5).limit == 5


def test_agent_tools_expose_only_read_only_enterprise_search_tools() -> None:
    definitions = agent_tool_definitions()

    assert [item["function"]["name"] for item in definitions] == [
        "searchProductsTool",
        "searchContentTool",
        "listKnowledgeBasesTool",
        "listKnowledgeFilesTool",
        "getKnowledgeBaseTool",
        "getKnowledgeFileTool",
        "searchKnowledgeBaseTool",
    ]
    assert all(item["function"]["parameters"]["type"] == "object" for item in definitions)


def test_disabled_knowledge_embeddings_do_not_expose_knowledge_base_tool() -> None:
    definitions = agent_tool_definitions(
        include_knowledge_base=True,
        include_knowledge_base_search=False,
    )

    assert [item["function"]["name"] for item in definitions] == [
        "searchProductsTool",
        "searchContentTool",
        "listKnowledgeBasesTool",
        "listKnowledgeFilesTool",
        "getKnowledgeBaseTool",
        "getKnowledgeFileTool",
    ]


def test_knowledge_search_query_filters_workspace_and_knowledge_base() -> None:
    sql = str(SEARCH_QUERY)

    assert 'chunk."workspaceId" = :workspace_id' in sql
    assert 'chunk."knowledgeBaseId" = :knowledge_base_id' in sql
    assert 'chunk."embedding" <=> CAST(:embedding AS vector)' in sql


def test_knowledge_search_route_keeps_workspace_and_base_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}
    connection = FakeSearchConnection(
        [
            {
                "chunk_id": CHUNK_A,
                "content": "pricing details",
                "file_id": FILE_A,
                "file_name": "pricing.csv",
                "score": 0.91,
            }
        ]
    )

    async def fake_require_permission(
        _current_user,
        workspace_id,
        knowledge_base_id,
        permission,
    ):
        captured.update(
            {
                "workspace_id": workspace_id,
                "knowledge_base_id": knowledge_base_id,
                "permission": permission,
            }
        )

    async def fake_embed_texts(_texts, _settings):
        return [[0.25] * 1536]

    monkeypatch.setattr(
        "app.api.routes.knowledge_search.require_knowledge_base_permission",
        fake_require_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_search.embed_texts",
        fake_embed_texts,
    )
    monkeypatch.setattr(
        "app.api.routes.knowledge_search.get_db_connection",
        search_connection_context(connection),
    )

    result = asyncio.run(
        search_knowledge_base(
            knowledge_base_id=KNOWLEDGE_BASE_A,
            payload=KnowledgeSearchRequest(query="pricing", limit=3),
            workspace_id=WORKSPACE_A,
            current_user=AuthenticatedUser(
                user_id="search-user",
                is_development=True,
            ),
            settings=Settings(
                environment="development",
                knowledge_embeddings_enabled=True,
            ),
        )
    )

    assert isinstance(result, KnowledgeSearchResponse)
    assert result.results[0].file_name == "pricing.csv"
    assert captured == {
        "workspace_id": WORKSPACE_A,
        "knowledge_base_id": KNOWLEDGE_BASE_A,
        "permission": "read",
    }

    query, params = connection.calls[0]
    assert 'chunk."workspaceId" = :workspace_id' in query
    assert 'chunk."knowledgeBaseId" = :knowledge_base_id' in query
    assert params["workspace_id"] == WORKSPACE_A
    assert params["knowledge_base_id"] == KNOWLEDGE_BASE_A
    assert params["limit"] == 3


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


def test_knowledge_file_list_tool_requires_a_valid_knowledge_base_id() -> None:
    with pytest.raises(ValueError):
        KnowledgeFileListToolInput.model_validate(
            {"knowledgeBaseId": "not-a-uuid"}
        )


def test_knowledge_base_lookup_tools_require_valid_ids() -> None:
    with pytest.raises(ValueError):
        KnowledgeBaseLookupToolInput.model_validate({"knowledgeBaseId": "invalid"})

    with pytest.raises(ValueError):
        KnowledgeFileLookupToolInput.model_validate(
            {"fileId": "invalid", "knowledgeBaseId": "invalid"}
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


def test_list_knowledge_bases_tool_calls_permission_checked_discovery(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_list_knowledge_bases(**kwargs):
        captured.update(kwargs)
        return KnowledgeBaseListResponse(knowledgeBases=[])

    monkeypatch.setattr(
        "app.services.agent_tools.list_knowledge_bases",
        fake_list_knowledge_bases,
    )

    result = asyncio.run(
        execute_agent_tool(
            "listKnowledgeBasesTool",
            {},
            current_user=AuthenticatedUser(user_id="development-user", is_development=True),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
        )
    )

    assert result == {"knowledgeBases": []}
    assert captured["workspace_id"] == UUID("00000000-0000-0000-0000-000000000001")
    assert captured["current_user"].is_development is True


def test_list_knowledge_files_tool_calls_permission_checked_listing(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_list_knowledge_files(**kwargs):
        captured.update(kwargs)
        return KnowledgeFileListResponse(files=[])

    monkeypatch.setattr(
        "app.services.agent_tools.list_knowledge_files",
        fake_list_knowledge_files,
    )

    result = asyncio.run(
        execute_agent_tool(
            "listKnowledgeFilesTool",
            {"knowledgeBaseId": "00000000-0000-0000-0000-000000000002"},
            current_user=AuthenticatedUser(user_id="development-user", is_development=True),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
        )
    )

    assert result == {"files": []}
    assert captured["knowledge_base_id"] == UUID(
        "00000000-0000-0000-0000-000000000002"
    )
    assert captured["workspace_id"] == UUID("00000000-0000-0000-0000-000000000001")


def test_get_knowledge_base_tool_returns_only_the_authorized_resource(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_list_knowledge_bases(**kwargs):
        captured.update(kwargs)
        return JSONResponse(
            content={
                "knowledgeBases": [
                    {
                        "knowledgeBaseId": "00000000-0000-0000-0000-000000000002",
                        "displayName": "Sales",
                        "sourceType": "manual",
                        "status": "ready",
                        "version": 1,
                        "workspaceId": "00000000-0000-0000-0000-000000000001",
                        "createdAt": "2026-08-17T12:30:00.000Z",
                        "updatedAt": "2026-08-17T12:30:00.000Z",
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "app.services.agent_tools.list_knowledge_bases",
        fake_list_knowledge_bases,
    )

    result = asyncio.run(
        execute_agent_tool(
            "getKnowledgeBaseTool",
            {"knowledgeBaseId": "00000000-0000-0000-0000-000000000002"},
            current_user=AuthenticatedUser(user_id="development-user", is_development=True),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
        )
    )

    assert result["knowledgeBase"]["displayName"] == "Sales"
    assert captured["workspace_id"] == UUID("00000000-0000-0000-0000-000000000001")


def test_get_knowledge_file_tool_returns_only_the_authorized_resource(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_list_knowledge_files(**kwargs):
        captured.update(kwargs)
        return JSONResponse(
            content={
                "files": [
                    {
                        "fileId": "00000000-0000-0000-0000-000000000003",
                        "knowledgeBaseId": "00000000-0000-0000-0000-000000000002",
                        "status": "ready",
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "app.services.agent_tools.list_knowledge_files",
        fake_list_knowledge_files,
    )

    result = asyncio.run(
        execute_agent_tool(
            "getKnowledgeFileTool",
            {
                "fileId": "00000000-0000-0000-0000-000000000003",
                "knowledgeBaseId": "00000000-0000-0000-0000-000000000002",
            },
            current_user=AuthenticatedUser(user_id="development-user", is_development=True),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
        )
    )

    assert result["file"]["status"] == "ready"
    assert captured["knowledge_base_id"] == UUID(
        "00000000-0000-0000-0000-000000000002"
    )


def test_get_knowledge_base_tool_rejects_a_resource_outside_authorized_listing(
    monkeypatch,
) -> None:
    async def fake_list_knowledge_bases(**kwargs):
        return JSONResponse(content={"knowledgeBases": []})

    monkeypatch.setattr(
        "app.services.agent_tools.list_knowledge_bases",
        fake_list_knowledge_bases,
    )

    with pytest.raises(AgentToolError, match="cannot access this knowledge base"):
        asyncio.run(
            execute_agent_tool(
                "getKnowledgeBaseTool",
                {"knowledgeBaseId": "00000000-0000-0000-0000-000000000002"},
                current_user=AuthenticatedUser(
                    user_id="development-user", is_development=True
                ),
                workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
                can_query_knowledge=True,
            )
        )


def test_get_knowledge_file_tool_rejects_a_resource_outside_authorized_listing(
    monkeypatch,
) -> None:
    async def fake_list_knowledge_files(**kwargs):
        return JSONResponse(content={"files": []})

    monkeypatch.setattr(
        "app.services.agent_tools.list_knowledge_files",
        fake_list_knowledge_files,
    )

    with pytest.raises(AgentToolError, match="cannot access this knowledge file"):
        asyncio.run(
            execute_agent_tool(
                "getKnowledgeFileTool",
                {
                    "fileId": "00000000-0000-0000-0000-000000000003",
                    "knowledgeBaseId": "00000000-0000-0000-0000-000000000002",
                },
                current_user=AuthenticatedUser(
                    user_id="development-user", is_development=True
                ),
                workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
                can_query_knowledge=True,
            )
        )


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
