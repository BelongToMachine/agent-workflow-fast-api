from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.workspace_access import require_workspace_permission
from app.services.agent_tools import AgentToolError, execute_agent_tool
from app.services.agent_workflow import AgentWorkflowError, run_agent_workflow

router = APIRouter(prefix="/agents", tags=["agents"])

AgentToolName = Literal[
    "getKnowledgeBaseTool",
    "getKnowledgeFileTool",
    "listKnowledgeFilesTool",
    "listKnowledgeBasesTool",
    "searchProductsTool",
    "searchContentTool",
    "searchKnowledgeBaseTool",
]


class AgentQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    arguments: dict[str, Any] = Field(default_factory=dict)
    tool: AgentToolName


class AgentQueryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    result: dict[str, Any]
    tool: AgentToolName


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    max_steps: int = Field(default=5, alias="maxSteps", ge=1, le=5)
    prompt: str = Field(min_length=1, max_length=10_000)


class AgentToolExecutionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    arguments: dict[str, Any]
    output: dict[str, Any]
    tool: str
    tool_call_id: str = Field(alias="toolCallId")


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    answer: str
    steps: int
    tool_calls: list[AgentToolExecutionResponse] = Field(alias="toolCalls")


@router.post("/query", response_model=AgentQueryResponse)
async def query_agent(
    payload: AgentQueryRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AgentQueryResponse | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.read")

    try:
        result = await execute_agent_tool(
            payload.tool,
            payload.arguments,
            can_query_knowledge=True,
            current_user=current_user,
            workspace_id=workspace_id,
        )
    except AgentToolError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": "agent:tool_error",
                "message": str(error),
                "tool": payload.tool,
            },
        )

    return AgentQueryResponse(result=result, tool=payload.tool)


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    payload: AgentRunRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AgentRunResponse | JSONResponse:
    workspace_access = await require_workspace_permission(
        current_user,
        workspace_id,
        "knowledge.read",
    )
    if not settings.deepseek_api_key:
        return JSONResponse(
            status_code=503,
            content={
                "code": "agent:provider_unavailable",
                "message": "DEEPSEEK_API_KEY is not configured for FastAPI.",
            },
        )

    try:
        result = await run_agent_workflow(
            prompt=payload.prompt,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.chat_model,
            current_user=current_user,
            workspace_id=workspace_id,
            can_query_knowledge="knowledge.read" in workspace_access.permissions,
            include_knowledge_base_search=settings.knowledge_embeddings_enabled,
            max_steps=payload.max_steps,
            timeout_seconds=settings.chat_provider_timeout_seconds,
        )
    except AgentWorkflowError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": "agent:workflow_error",
                "message": str(error),
            },
        )

    return AgentRunResponse(
        answer=result.answer,
        steps=result.steps,
        toolCalls=[
            AgentToolExecutionResponse(
                arguments=execution.arguments,
                output=execution.output,
                tool=execution.tool,
                toolCallId=execution.tool_call_id,
            )
            for execution in result.tool_calls
        ],
    )
