import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.api.routes.chat import (
    CHAT_ANY_BY_ID_QUERY,
    ChatRequest,
    UIMessage,
    _message_attachments,
    _message_payload,
    _prepare_chat_persistence,
    _resolve_workspace_id,
    chat,
    resume_chat_stream,
    stream_chat,
    to_openai_messages,
)
from app.api.routes.chats import (
    CHAT_BASE_CONDITIONS,
    CHAT_COLUMNS,
    ChatSummary,
    _chat_summary,
)
from app.core.auth import AuthenticatedUser
from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


class FakeChatResult:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []

    def mappings(self) -> "FakeChatResult":
        return self

    def first(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict[str, object]]:
        return self.rows


class FakeChatTransaction:
    async def __aenter__(self) -> "FakeChatTransaction":
        return self

    async def __aexit__(self, *_args) -> None:
        return None


class FakeChatConnection:
    def __init__(
        self,
        *,
        workspace_chat: dict[str, object] | None = None,
        any_workspace_chat: dict[str, object] | None = None,
    ) -> None:
        self.workspace_chat = workspace_chat
        self.any_workspace_chat = any_workspace_chat
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self,
        query: object,
        params: dict[str, object],
    ) -> FakeChatResult:
        sql = str(query)
        self.calls.append((sql, params))
        if 'FROM "Chat"' in sql and '"workspaceId" = :workspace_id' in sql:
            return FakeChatResult(
                [self.workspace_chat] if self.workspace_chat is not None else []
            )
        if 'FROM "Chat"' in sql and '"workspaceId" = :workspace_id' not in sql:
            return FakeChatResult(
                [self.any_workspace_chat]
                if self.any_workspace_chat is not None
                else []
            )
        return FakeChatResult()

    def begin(self) -> FakeChatTransaction:
        return FakeChatTransaction()


def chat_connection_context(connection: FakeChatConnection):
    @asynccontextmanager
    async def context():
        yield connection

    return context


class FakeResumeStore:
    def __init__(self, stream_id: str | None = "stream-1") -> None:
        self.stream_id = stream_id
        self.active_calls: list[str] = []
        self.resume_calls: list[tuple[str, str]] = []

    async def active_stream_id(self, chat_id: str) -> str | None:
        self.active_calls.append(chat_id)
        return self.stream_id

    def resume(self, chat_id: str, stream_id: str):
        self.resume_calls.append((chat_id, stream_id))

        async def source():
            yield "data: resumed\n\n"

        return source()


async def collect_stream(stream) -> list[str]:
    return [chunk async for chunk in stream]


@pytest.fixture
def auth_required_settings():
    settings = Settings(environment="development", auth_required=True)
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def test_chat_summary_matches_existing_nextjs_response_shape() -> None:
    summary = _chat_summary(
        {
            "id": UUID("00000000-0000-0000-0000-000000000010"),
            "created_at": datetime(2026, 8, 17, 12, 30),
            "title": "History",
            "user_id": UUID("00000000-0000-0000-0000-000000000011"),
            "visibility": "private",
            "workspace_id": UUID("00000000-0000-0000-0000-000000000012"),
        }
    )

    assert summary.model_dump(by_alias=True) == {
        "id": "00000000-0000-0000-0000-000000000010",
        "createdAt": "2026-08-17T12:30:00.000Z",
        "title": "History",
        "userId": "00000000-0000-0000-0000-000000000011",
        "visibility": "private",
        "workspaceId": "00000000-0000-0000-0000-000000000012",
    }


def test_chat_summary_rejects_missing_workspace_id() -> None:
    with pytest.raises(ValidationError):
        ChatSummary.model_validate(
            {
                "createdAt": "2026-08-17T12:30:00.000Z",
                "id": "00000000-0000-0000-0000-000000000010",
                "title": "History",
                "userId": "00000000-0000-0000-0000-000000000011",
                "visibility": "private",
            }
        )


def test_chat_query_is_scoped_by_user_and_workspace() -> None:
    assert 'chat."userId" = :user_id' in CHAT_BASE_CONDITIONS
    assert 'chat."workspaceId" = :workspace_id' in CHAT_BASE_CONDITIONS
    assert 'chat."workspaceId"' in CHAT_COLUMNS


def test_new_chat_creation_checks_for_an_existing_id_across_workspaces() -> None:
    assert 'FROM "Chat"' in str(CHAT_ANY_BY_ID_QUERY)
    assert 'WHERE "id" = :chat_id' in str(CHAT_ANY_BY_ID_QUERY)
    assert 'workspaceId' in str(CHAT_ANY_BY_ID_QUERY)


def test_history_requires_bearer_or_nextauth_bridge(auth_required_settings: Settings) -> None:
    response = client.get(
        "/api/v1/chats",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401


def test_history_rejects_two_cursors_before_database_access() -> None:
    response = client.get(
        "/api/v1/chats",
        params={
            "ending_before": "00000000-0000-0000-0000-000000000010",
            "starting_after": "00000000-0000-0000-0000-000000000011",
            "workspace_id": "00000000-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 400


def test_resume_stream_checks_workspace_and_owner_before_replay(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    chat_id = UUID("00000000-0000-0000-0000-000000000010")
    user_id = UUID("00000000-0000-0000-0000-000000000011")
    connection = FakeChatConnection(
        workspace_chat={
            "id": chat_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
        }
    )
    store = FakeResumeStore()
    captured_permission: dict[str, object] = {}

    async def fake_require_workspace_permission(
        current_user,
        requested_workspace_id,
        requested_permission,
    ):
        captured_permission.update(
            {
                "user_id": current_user.user_id,
                "workspace_id": requested_workspace_id,
                "permission": requested_permission,
            }
        )

    monkeypatch.setattr(
        "app.api.routes.chat.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_db_connection",
        chat_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_resumable_stream_store",
        lambda *_args: store,
    )

    response = asyncio.run(
        resume_chat_stream(
            chat_id=chat_id,
            workspace_id=workspace_id,
            current_user=AuthenticatedUser(user_id=str(user_id), role="employee"),
            settings=Settings(redis_url="redis://127.0.0.1:6379/0"),
        )
    )

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert asyncio.run(collect_stream(response.body_iterator)) == [
        "data: resumed\n\n"
    ]
    assert captured_permission == {
        "user_id": str(user_id),
        "workspace_id": workspace_id,
        "permission": "chat.read",
    }
    assert store.active_calls == [str(chat_id)]
    assert store.resume_calls == [(str(chat_id), "stream-1")]
    assert connection.calls[0][1] == {
        "chat_id": chat_id,
        "workspace_id": workspace_id,
    }


def test_resume_stream_rejects_chat_owned_by_another_user(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    chat_id = UUID("00000000-0000-0000-0000-000000000010")
    connection = FakeChatConnection(
        workspace_chat={
            "id": chat_id,
            "user_id": UUID("00000000-0000-0000-0000-000000000099"),
            "workspace_id": workspace_id,
        }
    )
    store = FakeResumeStore()

    async def fake_require_workspace_permission(*_args, **_kwargs):
        return SimpleNamespace(permissions=["chat.read"])

    monkeypatch.setattr(
        "app.api.routes.chat.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_db_connection",
        chat_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_resumable_stream_store",
        lambda *_args: store,
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            resume_chat_stream(
                chat_id=chat_id,
                workspace_id=workspace_id,
                current_user=AuthenticatedUser(
                    user_id="00000000-0000-0000-0000-000000000011",
                    role="employee",
                ),
                settings=Settings(redis_url="redis://127.0.0.1:6379/0"),
            )
        )

    assert getattr(error.value, "status_code", None) == 403
    assert "does not belong" in str(error.value.detail)
    assert store.active_calls == []
    assert store.resume_calls == []


def test_resume_stream_returns_no_content_for_another_workspace(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    chat_id = UUID("00000000-0000-0000-0000-000000000010")
    connection = FakeChatConnection()
    store = FakeResumeStore()

    async def fake_require_workspace_permission(*_args, **_kwargs):
        return SimpleNamespace(permissions=["chat.read"])

    monkeypatch.setattr(
        "app.api.routes.chat.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_db_connection",
        chat_connection_context(connection),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_resumable_stream_store",
        lambda *_args: store,
    )

    response = asyncio.run(
        resume_chat_stream(
            chat_id=chat_id,
            workspace_id=workspace_id,
            current_user=AuthenticatedUser(
                user_id="00000000-0000-0000-0000-000000000011",
                role="employee",
            ),
            settings=Settings(redis_url="redis://127.0.0.1:6379/0"),
        )
    )

    assert response.status_code == 204
    assert store.active_calls == []
    assert store.resume_calls == []
    assert connection.calls[0][1]["workspace_id"] == workspace_id


def test_chat_request_keeps_tool_parts_for_model_and_persistence() -> None:
    payload = ChatRequest.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "message": {
                "id": "00000000-0000-0000-0000-000000000011",
                "parts": [
                    {
                        "mediaType": "image/png",
                        "name": "brief.png",
                        "type": "file",
                        "url": "https://example.com/brief.png",
                    },
                    {"text": "Summarize this", "type": "text"},
                ],
                "role": "user",
            },
            "selectedChatModel": "deepseek-chat",
            "selectedVisibilityType": "private",
        }
    )

    assert _message_payload(payload.message)[1] == {
        "text": "Summarize this",
        "type": "text",
    }
    assert _message_attachments(payload.message) == [
        {
            "contentType": "image/png",
            "name": "brief.png",
            "url": "https://example.com/brief.png",
        }
    ]


def test_chat_converts_supported_image_parts_to_openai_multimodal_content() -> None:
    payload = ChatRequest.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "message": {
                "parts": [
                    {
                        "mediaType": "image/png",
                        "name": "brief.png",
                        "type": "file",
                        "url": "https://cdn.example.com/brief.png",
                    },
                    {"text": "Summarize this image", "type": "text"},
                ],
                "role": "user",
            },
        }
    )

    assert to_openai_messages(payload) == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Summarize this image"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://cdn.example.com/brief.png"},
                },
            ],
        }
    ]


def test_chat_does_not_forward_unsupported_or_untrusted_file_parts() -> None:
    payload = ChatRequest.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "message": {
                "parts": [
                    {
                        "mediaType": "application/pdf",
                        "name": "brief.pdf",
                        "type": "file",
                        "url": "https://cdn.example.com/brief.pdf",
                    },
                    {
                        "mediaType": "image/png",
                        "name": "private.png",
                        "type": "file",
                        "url": "file:///private/private.png",
                    },
                    {"text": "Only use supported images", "type": "text"},
                ],
                "role": "user",
            },
        }
    )

    assert to_openai_messages(payload) == [
        {"role": "user", "content": "Only use supported images"}
    ]


def test_chat_accepts_an_image_only_message_for_vision_models() -> None:
    payload = ChatRequest.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "message": {
                "parts": [
                    {
                        "mediaType": "image/jpeg",
                        "name": "photo.jpg",
                        "type": "file",
                        "url": "data:image/jpeg;base64,ZmFrZQ==",
                    }
                ],
                "role": "user",
            },
        }
    )

    assert to_openai_messages(payload)[0]["content"] == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
        }
    ]


def test_authenticated_chat_requires_workspace_context() -> None:
    user = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        role="editor",
    )

    with pytest.raises(Exception) as error:
        _resolve_workspace_id(user, None)

    assert getattr(error.value, "status_code", None) == 403


def test_development_chat_does_not_attempt_database_persistence() -> None:
    payload = ChatRequest(
        id="00000000-0000-0000-0000-000000000010",
        message={
            "id": "00000000-0000-0000-0000-000000000011",
            "parts": [{"text": "hello", "type": "text"}],
            "role": "user",
        },
    )
    user = AuthenticatedUser(user_id="development-user", is_development=True)

    persistence = asyncio.run(
        _prepare_chat_persistence(
            payload,
            user,
            UUID("00000000-0000-0000-0000-000000000001"),
        )
    )

    assert persistence is None


def test_authenticated_chat_persistence_scopes_new_chat_and_assistant_message(
    monkeypatch,
) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    chat_id = UUID("00000000-0000-0000-0000-000000000010")
    user_id = UUID("00000000-0000-0000-0000-000000000011")
    message_id = UUID("00000000-0000-0000-0000-000000000012")
    assistant_id = UUID("00000000-0000-0000-0000-000000000013")
    connection = FakeChatConnection()
    monkeypatch.setattr(
        "app.api.routes.chat.get_db_connection",
        chat_connection_context(connection),
    )

    persistence = asyncio.run(
        _prepare_chat_persistence(
            ChatRequest(
                id=str(chat_id),
                message=UIMessage(
                    id=str(message_id),
                    parts=[{"text": "Prepare a summary", "type": "text"}],
                    role="user",
                ),
                selectedVisibilityType="private",
            ),
            AuthenticatedUser(user_id=str(user_id), role="employee"),
            workspace_id,
        )
    )

    assert persistence is not None
    awaitable = persistence(str(assistant_id), "Summary is ready.")
    asyncio.run(awaitable)

    insert_calls = [
        (sql, params)
        for sql, params in connection.calls
        if 'INSERT INTO "Chat"' in sql or 'INSERT INTO "Message_v2"' in sql
    ]
    assert insert_calls[0][1] == {
        "chat_id": chat_id,
        "title": "New chat",
        "user_id": user_id,
        "visibility": "private",
        "workspace_id": workspace_id,
    }
    assert insert_calls[1][1] == {
        "attachments": "[]",
        "chat_id": chat_id,
        "message_id": message_id,
        "parts": '[{"type": "text", "text": "Prepare a summary"}]',
        "role": "user",
    }
    assert insert_calls[2][1]["attachments"] == "[]"
    assert insert_calls[2][1]["chat_id"] == chat_id
    assert insert_calls[2][1]["message_id"] == assistant_id
    assert insert_calls[2][1]["parts"] == (
        '[{"type": "text", "text": "Summary is ready."}]'
    )
    assert insert_calls[2][1]["role"] == "assistant"
    update_call = next(
        (params for sql, params in connection.calls if 'UPDATE "Chat"' in sql),
        None,
    )
    assert update_call == {
        "chat_id": chat_id,
        "title": "Prepare a summary",
        "user_id": user_id,
        "workspace_id": workspace_id,
    }
    assert all(
        params.get("workspace_id") == workspace_id
        for _sql, params in connection.calls
        if "workspace_id" in params
    )


def test_authenticated_chat_rejects_same_id_from_another_workspace(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    other_workspace_id = UUID("00000000-0000-0000-0000-000000000002")
    connection = FakeChatConnection(
        any_workspace_chat={
            "id": UUID("00000000-0000-0000-0000-000000000010"),
            "user_id": UUID("00000000-0000-0000-0000-000000000011"),
            "workspace_id": other_workspace_id,
        }
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_db_connection",
        chat_connection_context(connection),
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            _prepare_chat_persistence(
                ChatRequest(
                    id="00000000-0000-0000-0000-000000000010",
                    message=UIMessage(
                        parts=[{"text": "Do not cross workspace", "type": "text"}],
                        role="user",
                    ),
                ),
                AuthenticatedUser(
                    user_id="00000000-0000-0000-0000-000000000011",
                    role="employee",
                ),
                workspace_id,
            )
        )

    assert getattr(error.value, "status_code", None) == 403
    assert "workspace" in str(error.value.detail).lower()
    assert not any('INSERT INTO "Chat"' in sql for sql, _params in connection.calls)
    assert connection.calls[0][1]["workspace_id"] == workspace_id
    assert connection.calls[1][1] == {"chat_id": UUID("00000000-0000-0000-0000-000000000010")}


def test_authenticated_chat_rejects_chat_owned_by_another_user(monkeypatch) -> None:
    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    connection = FakeChatConnection(
        workspace_chat={
            "id": UUID("00000000-0000-0000-0000-000000000010"),
            "user_id": UUID("00000000-0000-0000-0000-000000000099"),
            "workspace_id": workspace_id,
        }
    )
    monkeypatch.setattr(
        "app.api.routes.chat.get_db_connection",
        chat_connection_context(connection),
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            _prepare_chat_persistence(
                ChatRequest(
                    id="00000000-0000-0000-0000-000000000010",
                    message=UIMessage(
                        parts=[{"text": "Do not impersonate", "type": "text"}],
                        role="user",
                    ),
                ),
                AuthenticatedUser(
                    user_id="00000000-0000-0000-0000-000000000011",
                    role="employee",
                ),
                workspace_id,
            )
        )

    assert getattr(error.value, "status_code", None) == 403
    assert "does not belong" in str(error.value.detail)
    assert len(connection.calls) == 1


def test_chat_route_falls_back_when_client_submits_an_unlisted_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_require_workspace_permission(*args, **kwargs):
        return SimpleNamespace(permissions=["chat.write", "knowledge.read"])

    async def fake_prepare_chat_persistence(*args, **kwargs):
        return None

    def fake_stream_chat(*args, **kwargs):
        captured["model"] = args[4]

        async def source():
            yield "data: done\n\n"

        return source()

    class FakeStreamStore:
        def capture(self, _chat_id, source):
            return source

    monkeypatch.setattr(
        "app.api.routes.chat.get_settings",
        lambda: Settings(deepseek_api_key="test-key", chat_model="deepseek-chat"),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.require_workspace_permission",
        fake_require_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.chat._prepare_chat_persistence",
        fake_prepare_chat_persistence,
    )
    monkeypatch.setattr("app.api.routes.chat.stream_chat", fake_stream_chat)
    monkeypatch.setattr(
        "app.api.routes.chat.get_resumable_stream_store",
        lambda *_args: FakeStreamStore(),
    )

    response = asyncio.run(
        chat(
            ChatRequest(
                id="00000000-0000-0000-0000-000000000010",
                message={
                    "parts": [{"text": "hello", "type": "text"}],
                    "role": "user",
                },
                selectedChatModel="untrusted-provider/model",
            ),
            request=Request({"type": "http", "headers": []}),
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            current_user=AuthenticatedUser(
                user_id="development-user", is_development=True
            ),
        )
    )

    assert response.status_code == 200
    assert captured["model"] == "deepseek-chat"


class FakeSseResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class FakeStreamingClient:
    def __init__(self, responses: list[FakeSseResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []
        self.timeout = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    def stream(self, _method: str, _url: str, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def test_stream_chat_emits_sse_tool_events_and_continues_with_provider_answer(monkeypatch) -> None:
    provider = FakeStreamingClient(
        [
            FakeSseResponse(
                [
                    "data: "
                    + json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": "call-1",
                                                "function": {
                                                    "name": "listKnowledgeBasesTool",
                                                    "arguments": "",
                                                },
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ),
                    "data: "
                    + json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "function": {"arguments": "{}"},
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ),
                    "data: [DONE]",
                ]
            ),
            FakeSseResponse(
                [
                    "data: "
                    + json.dumps(
                        {
                            "choices": [
                                {"delta": {"content": "Knowledge base ready."}}
                            ]
                        }
                    ),
                    "data: [DONE]",
                ]
            ),
        ]
    )
    captured: dict[str, object] = {}

    async def fake_execute_agent_tool(name, arguments, **kwargs):
        captured.update({"name": name, "arguments": arguments, **kwargs})
        return {"knowledgeBases": []}

    monkeypatch.setattr(
        "app.api.routes.chat.httpx.AsyncClient",
        lambda **kwargs: (setattr(provider, "timeout", kwargs["timeout"]) or provider),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.execute_agent_tool",
        fake_execute_agent_tool,
    )

    payload = ChatRequest(
        id="00000000-0000-0000-0000-000000000010",
        message={
            "parts": [{"text": "What is ready?", "type": "text"}],
            "role": "user",
        },
        selectedChatModel="untrusted-provider/model",
    )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in stream_chat(
                payload,
                "request-1",
                "test-key",
                "https://provider.example/v1",
                "deepseek-chat",
                AuthenticatedUser(user_id="development-user", is_development=True),
                UUID("00000000-0000-0000-0000-000000000001"),
                True,
                False,
                7.5,
            )
        ]

    chunks = asyncio.run(collect())

    assert provider.timeout == 7.5
    assert captured["name"] == "listKnowledgeBasesTool"
    assert any('"type": "tool-input-start"' in chunk for chunk in chunks)
    assert any('"type": "tool-output-available"' in chunk for chunk in chunks)
    assert any("Knowledge base ready." in chunk for chunk in chunks)
    assert any('"type": "finish"' in chunk for chunk in chunks)
    assert provider.requests[0]["json"]["model"] == "deepseek-chat"
    assert provider.requests[1]["json"]["messages"][-1]["role"] == "tool"


def test_messages_endpoint_has_workspace_scoped_development_fallback() -> None:
    response = client.get(
        "/api/v1/chats/00000000-0000-0000-0000-000000000010/messages",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "isReadonly": False,
        "messages": [],
        "userId": None,
        "visibility": "private",
    }
