import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.auth import AuthenticatedUser
from app.services.agent_tools import (
    AgentToolError,
    agent_tool_definitions,
    execute_agent_tool,
)


class AgentWorkflowError(Exception):
    """Raised when the independent agent cannot complete its bounded workflow."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AgentToolExecution:
    tool_call_id: str
    tool: str
    arguments: dict[str, Any]
    output: dict[str, Any]


@dataclass(frozen=True)
class AgentWorkflowResult:
    answer: str
    steps: int
    tool_calls: list[AgentToolExecution]


def _provider_error(response: httpx.Response) -> AgentWorkflowError:
    detail = response.text[:500]
    return AgentWorkflowError(
        f"The agent provider request failed ({response.status_code}): {detail}",
        status_code=502,
    )


def _message_from_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as error:
        raise AgentWorkflowError("The agent provider returned invalid JSON.") from error

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AgentWorkflowError("The agent provider returned no choices.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AgentWorkflowError("The agent provider returned an invalid message.")
    return message


def _tool_call_arguments(raw_arguments: object) -> dict[str, Any]:
    if not isinstance(raw_arguments, str):
        raise AgentToolError("Tool arguments must be a JSON object.")
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as error:
        raise AgentToolError("Tool arguments must be valid JSON.") from error
    if not isinstance(arguments, dict):
        raise AgentToolError("Tool arguments must be a JSON object.")
    return arguments


async def _run_with_client(
    *,
    client: Any,
    prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    can_query_knowledge: bool,
    include_knowledge_base_search: bool,
    max_steps: int,
    timeout_seconds: float,
) -> AgentWorkflowResult:
    conversation: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_executions: list[AgentToolExecution] = []
    tools = agent_tool_definitions(
        include_knowledge_base=can_query_knowledge,
        include_knowledge_base_search=include_knowledge_base_search,
    )

    for step in range(1, max_steps + 1):
        try:
            request_body: dict[str, Any] = {
                "model": model,
                "messages": conversation,
                "stream": False,
            }
            if tools:
                request_body["tool_choice"] = "auto"
                request_body["tools"] = tools
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=request_body,
            )
        except httpx.HTTPError as error:
            raise AgentWorkflowError(
                f"FastAPI could not reach the agent provider: {error}"
            ) from error

        if response.status_code >= 400:
            raise _provider_error(response)

        message = _message_from_response(response)
        content = message.get("content")
        raw_tool_calls = message.get("tool_calls")
        tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []

        if not tool_calls:
            if isinstance(content, str) and content.strip():
                return AgentWorkflowResult(
                    answer=content,
                    steps=step,
                    tool_calls=tool_executions,
                )
            raise AgentWorkflowError(
                "The agent provider returned neither an answer nor a tool call."
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content if isinstance(content, str) else None,
            "tool_calls": [],
        }
        normalized_tool_calls: list[dict[str, Any]] = []

        for index, raw_tool_call in enumerate(tool_calls):
            if not isinstance(raw_tool_call, dict):
                continue
            function = raw_tool_call.get("function")
            if not isinstance(function, dict):
                function = {}
            tool_call_id = str(raw_tool_call.get("id") or f"agent-call-{step}-{index}")
            tool_name = str(function.get("name") or "")
            raw_arguments = function.get("arguments", "{}")
            normalized_tool_calls.append(
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": raw_arguments,
                    },
                }
            )

            output: dict[str, Any]
            try:
                arguments = _tool_call_arguments(raw_arguments)
                output = await execute_agent_tool(
                    tool_name,
                    arguments,
                    can_query_knowledge=can_query_knowledge,
                    current_user=current_user,
                    workspace_id=workspace_id,
                )
            except AgentToolError as error:
                arguments = {}
                output = {"error": str(error)}

            tool_executions.append(
                AgentToolExecution(
                    tool_call_id=tool_call_id,
                    tool=tool_name,
                    arguments=arguments,
                    output=output,
                )
            )
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )

        if not normalized_tool_calls:
            raise AgentWorkflowError("The agent provider returned invalid tool calls.")

        assistant_message["tool_calls"] = normalized_tool_calls
        conversation.insert(len(conversation) - len(normalized_tool_calls), assistant_message)

    raise AgentWorkflowError(
        f"The agent reached its maximum of {max_steps} tool steps.",
        status_code=422,
    )


async def run_agent_workflow(
    *,
    prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    can_query_knowledge: bool,
    include_knowledge_base_search: bool,
    max_steps: int = 5,
    timeout_seconds: float = 60.0,
    client: Any | None = None,
) -> AgentWorkflowResult:
    if client is not None:
        return await _run_with_client(
            client=client,
            prompt=prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            current_user=current_user,
            workspace_id=workspace_id,
            can_query_knowledge=can_query_knowledge,
            include_knowledge_base_search=include_knowledge_base_search,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )

    async with httpx.AsyncClient(timeout=timeout_seconds) as provider_client:
        return await _run_with_client(
            client=provider_client,
            prompt=prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            current_user=current_user,
            workspace_id=workspace_id,
            can_query_knowledge=can_query_knowledge,
            include_knowledge_base_search=include_knowledge_base_search,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )
