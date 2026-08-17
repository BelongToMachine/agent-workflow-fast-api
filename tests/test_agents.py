import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.agents import AgentQueryRequest, AgentQueryResponse, query_agent
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app
from app.services.agent_tools import AgentToolError

client = TestClient(app)


def test_agent_query_contract_rejects_unknown_tools() -> None:
    with pytest.raises(ValidationError):
        AgentQueryRequest.model_validate(
            {"tool": "deleteEverythingTool", "arguments": {}}
        )


def test_agent_query_response_preserves_tool_and_result_shape() -> None:
    response = AgentQueryResponse(
        tool="searchProductsTool",
        result={"products": [], "source": "enterprise"},
    )

    assert response.model_dump() == {
        "tool": "searchProductsTool",
        "result": {"products": [], "source": "enterprise"},
    }


def test_agent_query_requires_authenticated_identity() -> None:
    settings = Settings(environment="development", auth_required=True)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.post(
            "/api/v1/agents/query",
            params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
            json={"tool": "searchProductsTool", "arguments": {"query": "chair"}},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 401


def test_agent_query_maps_tool_errors_without_exposing_identity_controls(monkeypatch) -> None:
    async def fake_require_workspace_permission(*args, **kwargs):
        return SimpleNamespace(permissions=["knowledge.read"])

    captured: dict[str, object] = {}

    async def fake_execute_agent_tool(name, arguments, **kwargs):
        captured.update({"name": name, "arguments": arguments, **kwargs})
        raise AgentToolError("The user cannot access this knowledge base.", status_code=403)

    monkeypatch.setattr(
        "app.api.routes.agents.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.agents.execute_agent_tool",
        fake_execute_agent_tool,
    )

    response = asyncio.run(
        query_agent(
            AgentQueryRequest(
                tool="searchKnowledgeBaseTool",
                arguments={"knowledgeBaseId": "00000000-0000-0000-0000-000000000002"},
            ),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            current_user=AuthenticatedUser(
                user_id="00000000-0000-0000-0000-000000000010",
                role="viewer",
            ),
        )
    )

    assert response.status_code == 403
    assert response.body == (
        b'{"code":"agent:tool_error","message":"The user cannot access this '
        b'knowledge base.","tool":"searchKnowledgeBaseTool"}'
    )
    assert captured["can_query_knowledge"] is True
    assert captured["current_user"].user_id == "00000000-0000-0000-0000-000000000010"
