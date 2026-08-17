import asyncio
from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.chat import (
    CHAT_ANY_BY_ID_QUERY,
    ChatRequest,
    _message_attachments,
    _message_payload,
    _prepare_chat_persistence,
    _resolve_workspace_id,
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
