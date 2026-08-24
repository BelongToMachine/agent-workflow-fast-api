import asyncio
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.errors import structured_http_exception_handler
from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


def test_missing_bearer_token_uses_a_structured_error_contract() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="production",
        auth_required=True,
    )
    try:
        response = client.get("/api/v1/me")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "code": "auth:token_missing",
        "detail": "Bearer access token is required.",
        "message": "Bearer access token is required.",
    }


def test_workspace_permission_denial_uses_a_stable_code() -> None:
    request = Request(
        {
            "headers": [],
            "method": "GET",
            "path": "/api/v1/chats",
            "scheme": "http",
            "server": ("testserver", 80),
            "type": "http",
        }
    )
    response = asyncio.run(
        structured_http_exception_handler(
            request,
            HTTPException(
                status_code=403,
                detail="The user does not have permission to access this workspace data.",
            ),
        )
    )

    assert response.status_code == 403
    assert json.loads(response.body) == {
        "code": "workspace:permission_denied",
        "detail": "The user does not have permission to access this workspace data.",
        "message": "The user does not have permission to access this workspace data.",
    }
