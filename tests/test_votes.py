import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes.votes import (
    CHAT_OWNER_QUERY,
    MESSAGE_QUERY,
    UPSERT_VOTE_QUERY,
    VOTES_QUERY,
    VoteRequest,
    _require_chat_owner,
)
from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


def test_vote_request_preserves_existing_payload_shape() -> None:
    payload = VoteRequest.model_validate(
        {
            "chatId": "00000000-0000-0000-0000-000000000010",
            "messageId": "00000000-0000-0000-0000-000000000011",
            "type": "up",
        }
    )

    assert payload.model_dump(by_alias=True) == {
        "chatId": UUID("00000000-0000-0000-0000-000000000010"),
        "messageId": UUID("00000000-0000-0000-0000-000000000011"),
        "type": "up",
    }


def test_vote_queries_scope_chat_and_message_to_the_owned_workspace() -> None:
    assert 'WHERE "id" = :chat_id' in str(CHAT_OWNER_QUERY)
    assert '"userId" AS user_id' in str(CHAT_OWNER_QUERY)
    assert '"workspaceId" AS workspace_id' in str(CHAT_OWNER_QUERY)
    assert '"chatId" = :chat_id' in str(MESSAGE_QUERY)
    assert 'WHERE "id" = :message_id' in str(MESSAGE_QUERY)
    assert 'WHERE "chatId" = :chat_id' in str(VOTES_QUERY)
    assert 'ON CONFLICT ("chatId", "messageId")' in str(UPSERT_VOTE_QUERY)


def test_development_get_votes_returns_empty_list() -> None:
    response = client.get(
        "/api/v1/votes",
        params={
            "chatId": "00000000-0000-0000-0000-000000000010",
            "workspace_id": "00000000-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 200
    assert response.json() == []


def test_development_save_vote_keeps_legacy_success_response() -> None:
    response = client.patch(
        "/api/v1/votes",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        json={
            "chatId": "00000000-0000-0000-0000-000000000010",
            "messageId": "00000000-0000-0000-0000-000000000011",
            "type": "down",
        },
    )

    assert response.status_code == 200
    assert response.text == "Message voted"


def test_vote_owner_check_rejects_a_different_workspace() -> None:
    class FakeMappings:
        def first(self):
            return {
                "user_id": UUID("00000000-0000-0000-0000-000000000010"),
                "workspace_id": UUID("00000000-0000-0000-0000-000000000099"),
            }

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeConnection:
        async def execute(self, *_args, **_kwargs):
            return FakeResult()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            _require_chat_owner(
                FakeConnection(),
                chat_id=UUID("00000000-0000-0000-0000-000000000020"),
                not_found_detail="Chat not found.",
                user_id=UUID("00000000-0000-0000-0000-000000000010"),
                workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            )
        )

    assert error.value.status_code == 403


def test_votes_require_authentication() -> None:
    settings = Settings(environment="development", auth_required=True)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.get(
            "/api/v1/votes",
            params={
                "chatId": "00000000-0000-0000-0000-000000000010",
                "workspace_id": "00000000-0000-0000-0000-000000000001",
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 401
