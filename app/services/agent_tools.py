import json
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.content import search_content
from app.api.routes.knowledge_search import (
    KnowledgeSearchRequest,
    search_knowledge_base,
)
from app.api.routes.products import search_products
from app.core.auth import AuthenticatedUser
from app.core.config import get_settings


class AgentToolError(Exception):
    """Raised when a server-side agent tool cannot safely execute."""


class ProductToolInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str | None = None
    has_document: bool | None = Field(default=None, alias="hasDocument")
    limit: int = Field(default=10, ge=1, le=20)
    logistics: str | None = None
    max_lead_days: int | None = Field(default=None, alias="maxLeadDays", gt=0)
    max_moq_units: int | None = Field(default=None, alias="maxMoqUnits", gt=0)
    max_price_usd: float | None = Field(default=None, alias="maxPriceUsd", ge=0)
    missing_field: Literal[
        "price",
        "supplier",
        "qualification",
        "document",
        "promotionStatus",
    ] | None = Field(default=None, alias="missingField")
    operation_status: str | None = Field(default=None, alias="operationStatus")
    proposer: str | None = None
    qualification: str | None = None
    query: str | None = None
    source_file_names: list[str] | None = Field(default=None, alias="sourceFileNames")
    target_channel: str | None = Field(default=None, alias="targetChannel")


class ContentToolInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account: str | None = None
    language: str | None = None
    limit: int = Field(default=10, ge=1, le=20)
    product: str | None = None
    query: str | None = None
    record_type: Literal["account", "copy", "edit_plan", "shoot_plan", "topic"] | None = Field(
        default=None,
        alias="recordType",
    )
    source_file_names: list[str] | None = Field(default=None, alias="sourceFileNames")
    status: str | None = None
    submitter: str | None = None


class KnowledgeBaseToolInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_base_id: UUID = Field(alias="knowledgeBaseId")
    limit: int = Field(default=8, ge=1, le=20)
    query: str = Field(min_length=1, max_length=2000)


def agent_tool_definitions(*, include_knowledge_base: bool = True) -> list[dict[str, Any]]:
    definitions = [
        {
            "type": "function",
            "function": {
                "name": "searchProductsTool",
                "description": (
                    "Search enterprise product research and operations data. "
                    "Use sourceFileNames when the user names source files."
                ),
                "parameters": ProductToolInput.model_json_schema(),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "searchContentTool",
                "description": (
                    "Search enterprise content operations data. "
                    "Use sourceFileNames when the user names source files."
                ),
                "parameters": ContentToolInput.model_json_schema(),
            },
        },
    ]
    if include_knowledge_base:
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": "searchKnowledgeBaseTool",
                    "description": (
                        "Search one authorized knowledge base using semantic search. "
                        "Only use a knowledgeBaseId that the current user is allowed to read."
                    ),
                    "parameters": KnowledgeBaseToolInput.model_json_schema(),
                },
            },
        )
    return definitions


def _response_payload(response: object) -> dict[str, Any]:
    if isinstance(response, JSONResponse):
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentToolError(
                "The enterprise search service returned an invalid response."
            ) from error
        if response.status_code >= 500:
            raise AgentToolError("Enterprise search is currently unavailable.")
        raise AgentToolError(str(payload.get("cause", "Enterprise search failed.")))
    if isinstance(response, BaseModel):
        return response.model_dump(by_alias=True)
    raise AgentToolError("The enterprise search service returned an unsupported response.")


async def execute_agent_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    can_query_knowledge: bool,
) -> dict[str, Any]:
    if not can_query_knowledge:
        raise AgentToolError("The current user is not allowed to query enterprise knowledge.")

    try:
        if name == "searchProductsTool":
            payload = ProductToolInput.model_validate(arguments)
            response = await search_products(
                _current_user=current_user,
                workspace_id=workspace_id,
                query=payload.query,
                category=payload.category,
                max_price_usd=payload.max_price_usd,
                max_lead_days=payload.max_lead_days,
                max_moq_units=payload.max_moq_units,
                operation_status=payload.operation_status,
                target_channel=payload.target_channel,
                proposer=payload.proposer,
                logistics=payload.logistics,
                qualification=payload.qualification,
                has_document=payload.has_document,
                missing_field=payload.missing_field,
                limit=payload.limit,
                source_file_names=payload.source_file_names,
            )
            return _response_payload(response)

        if name == "searchContentTool":
            payload = ContentToolInput.model_validate(
                {**arguments, "workspaceId": str(workspace_id)}
            )
            response = await search_content(payload, current_user)
            return _response_payload(response)

        if name == "searchKnowledgeBaseTool":
            payload = KnowledgeBaseToolInput.model_validate(arguments)
            response = await search_knowledge_base(
                knowledge_base_id=payload.knowledge_base_id,
                payload=KnowledgeSearchRequest(query=payload.query, limit=payload.limit),
                workspace_id=workspace_id,
                current_user=current_user,
                settings=get_settings(),
            )
            return _response_payload(response)
    except HTTPException as error:
        raise AgentToolError(str(error.detail)) from error
    except ValueError as error:
        raise AgentToolError("The tool arguments are invalid.") from error

    raise AgentToolError(f"Unknown agent tool: {name}")
