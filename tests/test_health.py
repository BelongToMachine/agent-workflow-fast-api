from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

import app.api.routes.health as health
from app.api.routes.chat import ChatRequest, to_openai_messages
from app.main import app

client = TestClient(app)


def test_read_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_health_check() -> None:
    response = client.get("/api/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Asianode FastAPI",
        "environment": "development",
    }


def test_readiness_check_requires_database() -> None:
    response = client.get("/api/v1/readyz", headers={"X-Request-ID": "ready-check-1"})

    assert response.status_code == 503
    assert response.json() == {
        "code": "database:unavailable",
        "detail": "The database is temporarily unavailable.",
        "message": "The database is temporarily unavailable.",
        "requestId": "ready-check-1",
    }
    assert response.headers["x-request-id"] == "ready-check-1"
    assert response.headers["retry-after"] == "1"


def test_readiness_check_uses_a_database_connection(monkeypatch) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: object) -> None:
            self.statements.append(str(statement))

    connection = FakeConnection()

    @asynccontextmanager
    async def fake_db_connection():
        yield connection

    monkeypatch.setattr(health, "get_db_connection", fake_db_connection)

    response = client.get("/api/v1/readyz")

    assert response.status_code == 200
    assert connection.statements == ["SELECT 1"]


def test_cors_allows_nextjs_development_origin() -> None:
    response = client.options(
        "/api/v1/healthz",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_products_requires_workspace_id() -> None:
    response = client.get("/api/v1/products")

    assert response.status_code == 422


def test_products_validates_limit() -> None:
    response = client.get(
        "/api/v1/products",
        params={
            "limit": 0,
            "workspace_id": "00000000-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 422


def test_chat_requires_a_text_message() -> None:
    response = client.post(
        "/api/v1/chat",
        json={"id": "chat-1", "message": {"role": "user", "parts": []}},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request:api"


def test_chat_preserves_multi_turn_context() -> None:
    payload = ChatRequest.model_validate(
        {
            "id": "chat-1",
            "messages": [
                {"role": "user", "parts": [{"type": "text", "text": "你好"}]},
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "text": "你好，有什么可以帮你？"}],
                },
                {"role": "user", "parts": [{"type": "text", "text": "继续"}]},
            ],
        }
    )

    assert to_openai_messages(payload) == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
        {"role": "user", "content": "继续"},
    ]
