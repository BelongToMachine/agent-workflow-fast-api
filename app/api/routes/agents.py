from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import require_workspace_permission
from app.services.agent_tools import AgentToolError, execute_agent_tool

router = APIRouter(prefix="/agents", tags=["agents"])

AgentToolName = Literal[
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
