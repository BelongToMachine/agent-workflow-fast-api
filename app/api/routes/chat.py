import json
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings

router = APIRouter(tags=["chat"])


class MessagePart(BaseModel):
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
    selectedVisibilityType: str | None = None


def get_text(message: UIMessage) -> str:
    return "".join(part.text or "" for part in message.parts if part.type == "text")


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
) -> AsyncIterator[str]:
    assistant_message_id = str(uuid4())

    yield sse_chunk({"type": "start", "messageId": assistant_message_id})
    yield sse_chunk({"type": "text-start", "id": assistant_message_id})

    request_body = {
        "model": payload.selectedChatModel or model,
        "messages": to_openai_messages(payload),
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
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
                                f"DeepSeek request failed ({response.status_code}): {detail[:500]}"
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

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield sse_chunk(
                            {
                                "type": "text-delta",
                                "id": assistant_message_id,
                                "delta": text,
                            }
                        )

        yield sse_chunk({"type": "text-end", "id": assistant_message_id})
        yield sse_chunk({"type": "finish", "finishReason": "stop"})
    except httpx.HTTPError as error:
        yield sse_chunk(
            {
                "type": "error",
                "errorText": f"FastAPI could not reach the model provider: {error}",
            }
        )


@router.post("/chat", response_model=None)
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse | JSONResponse:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    settings = get_settings()
    messages = to_openai_messages(payload)

    if not messages:
        return error_response("A text message is required.", request_id, 400)

    if not settings.deepseek_api_key:
        return error_response(
            "DEEPSEEK_API_KEY is not configured for FastAPI.", request_id, 503
        )

    return StreamingResponse(
        stream_chat(
            payload,
            request_id,
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.chat_model,
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
