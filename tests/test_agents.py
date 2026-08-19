import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.agents import (
    AgentQueryRequest,
    AgentQueryResponse,
    AgentRunRequest,
    AgentRunResponse,
    query_agent,
    run_agent,
)
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app
from app.services.agent_tools import AgentToolError
from app.services.agent_workflow import (
    AgentToolExecution,
    AgentWorkflowResult,
    run_agent_workflow,
)

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


def test_agent_run_request_limits_the_provider_tool_loop() -> None:
    with pytest.raises(ValidationError):
        AgentRunRequest.model_validate({"prompt": "search", "maxSteps": 11})

    assert AgentRunRequest.model_validate(
        {"prompt": "search", "maxSteps": 10}
    ).max_steps == 10

    response = AgentRunResponse(
        answer="The knowledge base is ready.",
        steps=2,
        toolCalls=[],
    )

    assert response.model_dump(by_alias=True) == {
        "answer": "The knowledge base is ready.",
        "steps": 2,
        "toolCalls": [],
    }


class FakeProviderResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    @property
    def text(self) -> str:
        return str(self._payload)

    def json(self) -> dict[str, object]:
        return self._payload


class FakeProviderClient:
    def __init__(self, responses: list[FakeProviderResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    async def post(self, _url: str, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def test_independent_agent_workflow_executes_authorized_tools_then_answers(monkeypatch) -> None:
    provider = FakeProviderClient(
        [
            FakeProviderResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "listKnowledgeBasesTool",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ),
            FakeProviderResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Sales knowledge base is ready.",
                                "tool_calls": [],
                            }
                        }
                    ]
                }
            ),
            FakeProviderResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Final summary: Sales knowledge base is ready.",
                                "tool_calls": [],
                            }
                        }
                    ]
                }
            ),
        ]
    )
    captured: dict[str, object] = {}

    async def fake_execute_agent_tool(name, arguments, **kwargs):
        captured.update({"name": name, "arguments": arguments, **kwargs})
        return {"knowledgeBases": [{"knowledgeBaseId": "kb-1"}]}

    monkeypatch.setattr(
        "app.services.agent_workflow.execute_agent_tool",
        fake_execute_agent_tool,
    )

    result = asyncio.run(
        run_agent_workflow(
            prompt="What is ready?",
            api_key="test-key",
            base_url="https://provider.example/v1",
            model="deepseek-chat",
            current_user=AuthenticatedUser(
                user_id="00000000-0000-0000-0000-000000000010"
            ),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
            include_knowledge_base_search=False,
            client=provider,
        )
    )

    assert result.answer == "Final summary: Sales knowledge base is ready."
    assert result.steps == 3
    assert result.tool_calls[0].tool == "listKnowledgeBasesTool"
    assert captured["workspace_id"] == UUID("00000000-0000-0000-0000-000000000001")
    assert provider.requests[0]["json"]["tools"]
    assert provider.requests[1]["json"]["messages"][-2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "listKnowledgeBasesTool", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"knowledgeBases": [{"knowledgeBaseId": "kb-1"}]}',
        },
    ]


def test_independent_agent_workflow_finalizes_after_the_configured_tool_limit() -> None:
    provider = FakeProviderClient(
        [
            FakeProviderResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "function": {
                                            "name": "listKnowledgeBasesTool",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ),
            FakeProviderResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Final answer.",
                                "tool_calls": [],
                            }
                        }
                    ]
                }
            ),
        ]
    )

    result = asyncio.run(
        run_agent_workflow(
            prompt="Search",
            api_key="test-key",
            base_url="https://provider.example/v1",
            model="deepseek-chat",
            current_user=AuthenticatedUser(
                user_id="00000000-0000-0000-0000-000000000010"
            ),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_query_knowledge=True,
            include_knowledge_base_search=False,
            max_steps=1,
            client=provider,
        )
    )

    assert result.answer == "Final answer."
    assert result.steps == 1
    assert "tools" not in provider.requests[-1]["json"]
    assert provider.requests[-1]["json"]["messages"][0]["role"] == "system"


def test_agent_run_route_keeps_workspace_and_permission_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_require_workspace_permission(*args, **kwargs):
        return SimpleNamespace(permissions=["knowledge.read"])

    async def fake_run_agent_workflow(**kwargs):
        captured.update(kwargs)
        return AgentWorkflowResult(
            answer="Done",
            steps=1,
            tool_calls=[
                AgentToolExecution(
                    tool_call_id="call-1",
                    tool="listKnowledgeBasesTool",
                    arguments={},
                    output={"knowledgeBases": []},
                )
            ],
        )

    monkeypatch.setattr(
        "app.api.routes.agents.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.agents.run_agent_workflow",
        fake_run_agent_workflow,
    )

    response = asyncio.run(
        run_agent(
            AgentRunRequest(prompt="List knowledge bases", maxSteps=2),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            current_user=AuthenticatedUser(
                user_id="00000000-0000-0000-0000-000000000010"
            ),
            settings=Settings(deepseek_api_key="test-key"),
        )
    )

    assert response.answer == "Done"
    assert response.model_dump(by_alias=True)["toolCalls"][0]["tool"] == (
        "listKnowledgeBasesTool"
    )
    assert captured["workspace_id"] == UUID("00000000-0000-0000-0000-000000000001")
    assert captured["can_query_knowledge"] is True


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
