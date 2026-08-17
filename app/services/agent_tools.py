import json
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.content import search_content
from app.api.routes.knowledge_bases import list_knowledge_bases
from app.api.routes.knowledge_files import list_knowledge_files
from app.api.routes.knowledge_search import (
    KnowledgeSearchRequest,
    search_knowledge_base,
)
from app.api.routes.products import search_products
from app.core.auth import AuthenticatedUser
from app.core.config import get_settings


class AgentToolError(Exception):
    """Raised when a server-side agent tool cannot safely execute."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


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


class KnowledgeFileListToolInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_base_id: UUID = Field(alias="knowledgeBaseId")


class KnowledgeBaseLookupToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    knowledge_base_id: UUID = Field(alias="knowledgeBaseId")


class KnowledgeFileLookupToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    file_id: UUID = Field(alias="fileId")
    knowledge_base_id: UUID = Field(alias="knowledgeBaseId")


class ListKnowledgeBasesToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def agent_tool_definitions(
    *,
    include_knowledge_base: bool = True,
    include_knowledge_base_search: bool | None = None,
) -> list[dict[str, Any]]:
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
                    "name": "listKnowledgeBasesTool",
                    "description": (
                        "List knowledge bases the current user can read in the current workspace. "
                        "Use the returned knowledgeBaseId with searchKnowledgeBaseTool."
                    ),
                    "parameters": ListKnowledgeBasesToolInput.model_json_schema(),
                },
            },
        )
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": "listKnowledgeFilesTool",
                    "description": (
                        "List files and processing status in one authorized knowledge base. "
                        "Only use a knowledgeBaseId returned by listKnowledgeBasesTool."
                    ),
                    "parameters": KnowledgeFileListToolInput.model_json_schema(),
                },
            },
        )
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": "getKnowledgeBaseTool",
                    "description": (
                        "Get one knowledge base the current user can read. "
                        "Only use a knowledgeBaseId returned by listKnowledgeBasesTool."
                    ),
                    "parameters": KnowledgeBaseLookupToolInput.model_json_schema(),
                },
            },
        )
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": "getKnowledgeFileTool",
                    "description": (
                        "Get one authorized knowledge file and its processing status. "
                        "Only use a fileId and knowledgeBaseId returned by the knowledge file list."
                    ),
                    "parameters": KnowledgeFileLookupToolInput.model_json_schema(),
                },
            },
        )
        if include_knowledge_base_search is None:
            include_knowledge_base_search = True
    if include_knowledge_base and include_knowledge_base_search:
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
            raise AgentToolError(
                "Enterprise search is currently unavailable.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            message = (
                payload.get("cause")
                or payload.get("message")
                or payload.get("detail")
                or "Enterprise search failed."
            )
            raise AgentToolError(str(message), status_code=response.status_code)
        if not isinstance(payload, dict):
            raise AgentToolError(
                "The enterprise search service returned an unsupported response."
            )
        return payload
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

        if name == "getKnowledgeBaseTool":
            payload = KnowledgeBaseLookupToolInput.model_validate(arguments)
            response = await list_knowledge_bases(
                workspace_id=workspace_id,
                current_user=current_user,
                settings=get_settings(),
            )
            result = _response_payload(response)
            knowledge_bases = result.get("knowledgeBases", [])
            selected = next(
                (
                    item
                    for item in knowledge_bases
                    if item.get("knowledgeBaseId") == str(payload.knowledge_base_id)
                ),
                None,
            )
            if selected is None:
                raise AgentToolError(
                    "The user cannot access this knowledge base.",
                    status_code=404,
                )
            return {"knowledgeBase": selected}

        if name == "getKnowledgeFileTool":
            payload = KnowledgeFileLookupToolInput.model_validate(arguments)
            response = await list_knowledge_files(
                knowledge_base_id=payload.knowledge_base_id,
                workspace_id=workspace_id,
                current_user=current_user,
                settings=get_settings(),
            )
            result = _response_payload(response)
            files = result.get("files", [])
            selected = next(
                (
                    item
                    for item in files
                    if item.get("fileId") == str(payload.file_id)
                ),
                None,
            )
            if selected is None:
                raise AgentToolError(
                    "The user cannot access this knowledge file.",
                    status_code=404,
                )
            return {"file": selected}

        if name == "listKnowledgeBasesTool":
            ListKnowledgeBasesToolInput.model_validate(arguments)
            response = await list_knowledge_bases(
                workspace_id=workspace_id,
                current_user=current_user,
                settings=get_settings(),
            )
            return _response_payload(response)

        if name == "listKnowledgeFilesTool":
            payload = KnowledgeFileListToolInput.model_validate(arguments)
            response = await list_knowledge_files(
                knowledge_base_id=payload.knowledge_base_id,
                workspace_id=workspace_id,
                current_user=current_user,
                settings=get_settings(),
            )
            return _response_payload(response)
    except HTTPException as error:
        raise AgentToolError(str(error.detail), status_code=error.status_code) from error
    except ValueError as error:
        raise AgentToolError("The tool arguments are invalid.") from error

    raise AgentToolError(f"Unknown agent tool: {name}")
