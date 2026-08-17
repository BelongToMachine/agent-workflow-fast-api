from fastapi.testclient import TestClient

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
