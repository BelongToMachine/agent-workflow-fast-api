import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.chats import _database_error, _iso_timestamp
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection
from app.services.agent_tools import (
    AgentToolError,
    agent_tool_definitions,
    execute_agent_tool,
)
from app.services.resumable_streams import get_resumable_stream_store

router = APIRouter(tags=["chat"])


class MessagePart(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    text: str | None = None


class UIMessage(BaseModel):
    id: str | None = None
    role: str
    parts: list[MessagePart] = Field(default_factory=list)


class ChatRequest(BaseModel):
    id: str
    message: UIMessage | None = None
    messages: list[UIMessage] | None = None
    selectedChatModel: str | None = None
    selectedVisibilityType: Literal["public", "private"] | None = None


class StoredMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: str
    parts: list[dict[str, Any]]
    metadata: dict[str, str]


class ChatMessagesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    is_readonly: bool = Field(alias="isReadonly")
    messages: list[StoredMessage]
    user_id: str | None = Field(alias="userId")
    visibility: str


CHAT_BY_ID_QUERY = text(
    """
    SELECT "id", "title", "userId" AS user_id, "visibility", "workspaceId" AS workspace_id
    FROM "Chat"
    WHERE "id" = :chat_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

CHAT_ANY_BY_ID_QUERY = text(
    """
    SELECT "id", "userId" AS user_id, "workspaceId" AS workspace_id
    FROM "Chat"
    WHERE "id" = :chat_id
    LIMIT 1
    """
)

MESSAGES_QUERY = text(
    """
    SELECT "id", "role", "parts", "createdAt" AS created_at
    FROM "Message_v2"
    WHERE "chatId" = :chat_id
    ORDER BY "createdAt" ASC
    """
)

INSERT_CHAT_QUERY = text(
    """
    INSERT INTO "Chat" ("id", "createdAt", "title", "userId", "visibility", "workspaceId")
    VALUES (:chat_id, CURRENT_TIMESTAMP, :title, :user_id, :visibility, :workspace_id)
    ON CONFLICT ("id") DO NOTHING
    """
)

INSERT_MESSAGE_QUERY = text(
    """
    INSERT INTO "Message_v2" ("id", "chatId", "role", "parts", "attachments", "createdAt")
    VALUES (
        :message_id,
        :chat_id,
        :role,
        CAST(:parts AS json),
        CAST(:attachments AS json),
        CURRENT_TIMESTAMP
    )
    ON CONFLICT ("id") DO NOTHING
    """
)

UPDATE_CHAT_TITLE_QUERY = text(
    """
    UPDATE "Chat"
    SET "title" = :title
    WHERE "id" = :chat_id
      AND "userId" = :user_id
      AND "workspaceId" = :workspace_id
      AND "title" = 'New chat'
    """
)


def get_text(message: UIMessage) -> str:
    return "".join(
        part.text or "" for part in message.parts if part.type == "text"
    )


def to_openai_messages(payload: ChatRequest) -> list[dict[str, str]]:
    messages = payload.messages or ([payload.message] if payload.message else [])

    return [
        {"role": message.role, "content": get_text(message)}
        for message in messages
        if message.role in {"user", "assistant", "system"} and get_text(message)
    ]


def sse_chunk(chunk: dict[str, object]) -> str:
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def error_response(message: str, request_id: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "cause": message,
            "code": "offline:chat" if status_code >= 500 else "bad_request:api",
            "requestId": request_id,
        },
        headers={"x-request-id": request_id, "x-backend": "fastapi"},
    )


async def stream_chat(
    payload: ChatRequest,
    request_id: str,
    api_key: str,
    base_url: str,
    model: str,
    current_user: AuthenticatedUser,
    workspace_id: UUID,
    can_query_knowledge: bool,
    include_knowledge_base_tool: bool,
    on_complete: Callable[[str, str], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    assistant_message_id = str(uuid4())
    assistant_text: list[str] = []
    conversation = to_openai_messages(payload)

    yield sse_chunk({"type": "start", "messageId": assistant_message_id})
    yield sse_chunk({"type": "text-start", "id": assistant_message_id})

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            for _ in range(5):
                request_body: dict[str, Any] = {
                    "model": payload.selectedChatModel or model,
                    "messages": conversation,
                    "stream": True,
                }
                if can_query_knowledge:
                    request_body["tools"] = agent_tool_definitions(
                        include_knowledge_base=True,
                        include_knowledge_base_search=include_knowledge_base_tool,
                    )
                    request_body["tool_choice"] = "auto"

                tool_calls: dict[int, dict[str, str]] = {}
                step_text: list[str] = []
                async with client.stream(
                    "POST",
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request_body,
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")
                        yield sse_chunk(
                            {
                                "type": "error",
                                "errorText": (
                                    "DeepSeek request failed "
                                    f"({response.status_code}): {detail[:500]}"
                                ),
                            }
                        )
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue

                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices or not isinstance(choices[0], dict):
                            continue
                        delta = choices[0].get("delta", {})
                        if not isinstance(delta, dict):
                            continue
                        text_delta = delta.get("content")
                        if isinstance(text_delta, str) and text_delta:
                            assistant_text.append(text_delta)
                            step_text.append(text_delta)
                            yield sse_chunk(
                                {
                                    "type": "text-delta",
                                    "id": assistant_message_id,
                                    "delta": text_delta,
                                }
                            )

                        raw_tool_calls = delta.get("tool_calls", [])
                        if not isinstance(raw_tool_calls, list):
                            continue
                        for raw_tool_call in raw_tool_calls:
                            if not isinstance(raw_tool_call, dict):
                                continue
                            index = raw_tool_call.get("index", 0)
                            if not isinstance(index, int):
                                continue
                            function = raw_tool_call.get("function", {})
                            if not isinstance(function, dict):
                                function = {}
                            state = tool_calls.setdefault(
                                index,
                                {
                                    "id": str(raw_tool_call.get("id") or uuid4()),
                                    "name": str(function.get("name") or ""),
                                    "arguments": "",
                                },
                            )
                            if function.get("name"):
                                state["name"] = str(function["name"])
                            argument_delta = function.get("arguments")
                            if isinstance(argument_delta, str) and argument_delta:
                                if not state["arguments"]:
                                    yield sse_chunk(
                                        {
                                            "type": "tool-input-start",
                                            "toolCallId": state["id"],
                                            "toolName": state["name"],
                                        }
                                    )
                                state["arguments"] += argument_delta
                                yield sse_chunk(
                                    {
                                        "type": "tool-input-delta",
                                        "toolCallId": state["id"],
                                        "inputTextDelta": argument_delta,
                                    }
                                )

                if not tool_calls:
                    break

                ordered_tool_calls = [tool_calls[index] for index in sorted(tool_calls)]
                conversation.append(
                    {
                        "role": "assistant",
                        "content": "".join(step_text) or None,
                        "tool_calls": [
                            {
                                "id": tool_call["id"],
                                "type": "function",
                                "function": {
                                    "arguments": tool_call["arguments"],
                                    "name": tool_call["name"],
                                },
                            }
                            for tool_call in ordered_tool_calls
                        ],
                    }
                )
                for tool_call in ordered_tool_calls:
                    parsed_arguments: dict[str, Any]
                    try:
                        raw_arguments = json.loads(tool_call["arguments"] or "{}")
                        if not isinstance(raw_arguments, dict):
                            raise AgentToolError("Tool arguments must be a JSON object.")
                        parsed_arguments = raw_arguments
                        output = await execute_agent_tool(
                            tool_call["name"],
                            parsed_arguments,
                            can_query_knowledge=can_query_knowledge,
                            current_user=current_user,
                            workspace_id=workspace_id,
                        )
                    except (AgentToolError, json.JSONDecodeError) as error:
                        parsed_arguments = {}
                        output = {"error": str(error)}
                    yield sse_chunk(
                        {
                            "type": "tool-input-available",
                            "toolCallId": tool_call["id"],
                            "toolName": tool_call["name"],
                            "input": parsed_arguments,
                        }
                    )
                    yield sse_chunk(
                        {
                            "type": "tool-output-available",
                            "toolCallId": tool_call["id"],
                            "output": output,
                        }
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(output, ensure_ascii=False),
                        }
                    )

        yield sse_chunk({"type": "text-end", "id": assistant_message_id})
        yield sse_chunk({"type": "finish", "finishReason": "stop"})
        if on_complete and assistant_text:
            await on_complete(assistant_message_id, "".join(assistant_text))
    except httpx.HTTPError as error:
        yield sse_chunk(
            {
                "type": "error",
                "errorText": f"FastAPI could not reach the model provider: {error}",
            }
        )


@router.post("/chat", response_model=None)
async def chat(
    payload: ChatRequest,
    request: Request,
    workspace_id: UUID | None = Query(default=None, alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> StreamingResponse | JSONResponse:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    settings = get_settings()
    messages = to_openai_messages(payload)

    if not messages:
        return error_response("A text message is required.", request_id, 400)

    if not settings.deepseek_api_key:
        return error_response("DEEPSEEK_API_KEY is not configured for FastAPI.", request_id, 503)

    effective_workspace_id = _resolve_workspace_id(current_user, workspace_id)
    workspace_access = await require_workspace_permission(
        current_user,
        effective_workspace_id,
        "chat.write",
    )
    persistence = await _prepare_chat_persistence(
        payload,
        current_user,
        effective_workspace_id,
    )

    stream_store = get_resumable_stream_store(
        settings.redis_url,
        settings.resumable_stream_ttl_seconds,
    )
    return StreamingResponse(
        stream_store.capture(
            payload.id,
            stream_chat(
                payload,
                request_id,
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.chat_model,
                current_user,
                effective_workspace_id,
                "knowledge.read" in workspace_access.permissions,
                settings.knowledge_embeddings_enabled,
                on_complete=persistence,
            ),
        ),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
            "x-backend": "fastapi",
            "x-request-id": request_id,
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )


@router.get("/chat/{chat_id}/stream", response_model=None)
async def resume_chat_stream(
    chat_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse | Response | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "chat.read")
    if current_user.is_development:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                CHAT_BY_ID_QUERY,
                {"chat_id": chat_id, "workspace_id": workspace_id},
            )
            chat_row = result.mappings().first()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not verify the chat stream owner.")

    if chat_row is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if chat_row["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The chat does not belong to this user.",
        )

    stream_store = get_resumable_stream_store(
        settings.redis_url,
        settings.resumable_stream_ttl_seconds,
    )
    stream_id = await stream_store.active_stream_id(str(chat_id))
    if stream_id is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return StreamingResponse(
        stream_store.resume(str(chat_id), stream_id),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
            "x-backend": "fastapi",
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )


def _resolve_workspace_id(
    current_user: AuthenticatedUser,
    workspace_id: UUID | None,
) -> UUID:
    if current_user.is_development:
        return workspace_id or UUID("00000000-0000-0000-0000-000000000001")

    token_workspace_id: UUID | None = None
    if current_user.workspace_id:
        try:
            token_workspace_id = UUID(current_user.workspace_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The authenticated user has an invalid workspace context.",
            ) from error

    if workspace_id and token_workspace_id and workspace_id != token_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The requested workspace does not match the authenticated context.",
        )
    if workspace_id:
        return workspace_id
    if token_workspace_id:
        return token_workspace_id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="A workspace context is required for authenticated chat requests.",
    )


def _message_payload(message: UIMessage) -> list[dict[str, Any]]:
    return [part.model_dump(exclude_none=True) for part in message.parts]


def _message_attachments(message: UIMessage) -> list[dict[str, str]]:
    return [
        {
            "contentType": str(part.model_dump().get("mediaType", "")),
            "name": str(part.model_dump().get("name", "")),
            "url": str(part.model_dump().get("url", "")),
        }
        for part in message.parts
        if part.type == "file"
    ]


async def _prepare_chat_persistence(
    payload: ChatRequest,
    current_user: AuthenticatedUser,
    workspace_id: UUID,
) -> Callable[[str, str], Awaitable[None]] | None:
    if current_user.is_development:
        return None

    try:
        user_id = UUID(current_user.user_id)
        chat_id = UUID(payload.id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user or chat ID is invalid.",
        ) from error

    user_message = payload.message
    if user_message is None and payload.messages:
        last_message = payload.messages[-1]
        if last_message.role == "user":
            user_message = last_message

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                chat_result = await connection.execute(
                    CHAT_BY_ID_QUERY,
                    {"chat_id": chat_id, "workspace_id": workspace_id},
                )
                chat_row = chat_result.mappings().first()
                if chat_row is not None and chat_row["user_id"] != user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="The chat does not belong to this user.",
                    )

                if chat_row is None:
                    existing_chat_result = await connection.execute(
                        CHAT_ANY_BY_ID_QUERY,
                        {"chat_id": chat_id},
                    )
                    if existing_chat_result.mappings().first() is not None:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="The chat does not belong to this workspace.",
                        )
                    if user_message is None or user_message.role != "user":
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Chat not found in this workspace.",
                        )
                    await connection.execute(
                        INSERT_CHAT_QUERY,
                        {
                            "chat_id": chat_id,
                            "title": "New chat",
                            "user_id": user_id,
                            "visibility": payload.selectedVisibilityType or "private",
                            "workspace_id": workspace_id,
                        },
                    )

                if user_message is not None and user_message.role == "user":
                    message_id = _message_id(user_message)
                    await connection.execute(
                        INSERT_MESSAGE_QUERY,
                        {
                            "attachments": json.dumps(_message_attachments(user_message)),
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "parts": json.dumps(_message_payload(user_message)),
                            "role": "user",
                        },
                    )
                    title = get_text(user_message).strip().replace("\n", " ")[:80]
                    if title:
                        await connection.execute(
                            UPDATE_CHAT_TITLE_QUERY,
                            {
                                "chat_id": chat_id,
                                "title": title,
                                "user_id": user_id,
                                "workspace_id": workspace_id,
                            },
                        )
    except HTTPException:
        raise
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not connect to the chat database.",
        ) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not persist the chat message.",
        ) from error

    async def save_assistant_message(message_id: str, text_content: str) -> None:
        try:
            async with get_db_connection() as connection:
                async with connection.begin():
                    await connection.execute(
                        INSERT_MESSAGE_QUERY,
                        {
                            "attachments": "[]",
                            "chat_id": chat_id,
                            "message_id": UUID(message_id),
                            "parts": json.dumps(
                                [{"type": "text", "text": text_content}],
                                ensure_ascii=False,
                            ),
                            "role": "assistant",
                        },
                    )
        except (RuntimeError, SQLAlchemyError):
            # The model stream has already completed; persistence failure is logged by
            # the caller in a later observability pass and must not corrupt the SSE.
            return

    return save_assistant_message


def _message_id(message: UIMessage) -> UUID:
    if not message.id:
        return uuid4()
    try:
        return UUID(message.id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message ID must be a UUID.",
        ) from error


@router.get("/chats/{chat_id}/messages", response_model=ChatMessagesResponse)
async def get_chat_messages(
    chat_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ChatMessagesResponse | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "chat.read")
    if current_user.is_development:
        return ChatMessagesResponse(
            isReadonly=False,
            messages=[],
            userId=None,
            visibility="private",
        )

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    try:
        async with get_db_connection() as connection:
            chat_result = await connection.execute(
                CHAT_BY_ID_QUERY,
                {"chat_id": chat_id, "workspace_id": workspace_id},
            )
            chat_row = chat_result.mappings().first()
            if chat_row is None:
                return ChatMessagesResponse(
                    isReadonly=False,
                    messages=[],
                    userId=None,
                    visibility="private",
                )
            if chat_row["user_id"] != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The chat does not belong to this user.",
                )

            message_result = await connection.execute(
                MESSAGES_QUERY,
                {"chat_id": chat_id},
            )
            messages = [
                StoredMessage(
                    id=str(row["id"]),
                    role=str(row["role"]),
                    parts=row["parts"] if isinstance(row["parts"], list) else [],
                    metadata={"createdAt": _iso_timestamp(row["created_at"])},
                )
                for row in message_result.mappings().all()
            ]
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query chat messages.")

    return ChatMessagesResponse(
        isReadonly=False,
        messages=messages,
        userId=str(user_id),
        visibility=str(chat_row["visibility"]),
    )
