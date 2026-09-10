from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.csrf import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    CSRFMiddleware,
    generate_csrf_token,
)
from app.core.sessions import SESSION_COOKIE_NAME


def _app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(
        CSRFMiddleware,
        allowed_origins=["http://localhost:5173"],
    )

    @application.post("/api/v1/mutation")
    async def mutation() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/api/v1/read")
    async def read() -> dict[str, bool]:
        return {"ok": True}

    return application


def test_cookie_session_mutation_requires_csrf_token() -> None:
    client = TestClient(_app())

    response = client.post(
        "/api/v1/mutation",
        cookies={SESSION_COOKIE_NAME: "active-session"},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "csrf:token_invalid"


def test_cookie_session_mutation_accepts_matching_csrf_cookie_and_header() -> None:
    client = TestClient(_app())
    token = generate_csrf_token()

    response = client.post(
        "/api/v1/mutation",
        cookies={
            SESSION_COOKIE_NAME: "active-session",
            CSRF_COOKIE_NAME: token,
        },
        headers={
            "Origin": "http://localhost:5173",
            CSRF_HEADER_NAME: token,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_cookie_session_mutation_rejects_an_untrusted_origin() -> None:
    client = TestClient(_app())
    token = generate_csrf_token()

    response = client.post(
        "/api/v1/mutation",
        cookies={
            SESSION_COOKIE_NAME: "active-session",
            CSRF_COOKIE_NAME: token,
        },
        headers={
            "Origin": "https://evil.example",
            CSRF_HEADER_NAME: token,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "csrf:origin_invalid"


def test_cookie_session_read_does_not_require_csrf_token() -> None:
    client = TestClient(_app())

    response = client.get(
        "/api/v1/read",
        cookies={SESSION_COOKIE_NAME: "active-session"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
