import asyncio
import logging
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

import app.db.session as session
from app.api.errors import database_service_error_handler
from app.core.request_context import RequestContextMiddleware
from app.db.errors import DatabaseTimeoutError, DatabaseUnavailableError
from app.db.session import get_db_connection


class _FakeConnection:
    async def execute(self, _statement: object) -> None:
        return None


class _FakeEngine:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error

    @asynccontextmanager
    async def connect(self):
        if self.error is not None:
            raise self.error
        yield _FakeConnection()


def test_database_connection_timeout_is_normalized(monkeypatch) -> None:
    monkeypatch.setattr(session, "get_engine", lambda: _FakeEngine(TimeoutError()))

    async def access_database() -> None:
        async with get_db_connection():
            pass

    with pytest.raises(DatabaseTimeoutError):
        asyncio.run(access_database())


def test_database_pool_timeout_is_normalized(monkeypatch) -> None:
    monkeypatch.setattr(
        session,
        "get_engine",
        lambda: _FakeEngine(SQLAlchemyTimeoutError("pool exhausted")),
    )

    async def access_database() -> None:
        async with get_db_connection():
            pass

    with pytest.raises(DatabaseTimeoutError):
        asyncio.run(access_database())


def test_database_command_timeout_is_normalized(monkeypatch) -> None:
    class TimeoutConnection:
        async def execute(self, _statement: object) -> None:
            raise TimeoutError()

    class TimeoutEngine:
        @asynccontextmanager
        async def connect(self):
            yield TimeoutConnection()

    monkeypatch.setattr(session, "get_engine", TimeoutEngine)

    async def access_database() -> None:
        async with get_db_connection() as connection:
            await connection.execute("SELECT 1")

    with pytest.raises(DatabaseTimeoutError):
        asyncio.run(access_database())


def test_non_timeout_sqlalchemy_errors_keep_route_specific_handling(monkeypatch) -> None:
    class FailingConnection:
        async def execute(self, _statement: object) -> None:
            raise SQLAlchemyError("query failed")

    class FailingEngine:
        @asynccontextmanager
        async def connect(self):
            yield FailingConnection()

    monkeypatch.setattr(session, "get_engine", FailingEngine)

    async def access_database() -> None:
        async with get_db_connection() as connection:
            await connection.execute("SELECT 1")

    with pytest.raises(SQLAlchemyError, match="query failed"):
        asyncio.run(access_database())


def test_database_timeout_response_has_a_stable_contract() -> None:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    application.add_exception_handler(DatabaseTimeoutError, database_service_error_handler)

    @application.get("/timeout")
    async def raise_timeout() -> None:
        raise DatabaseTimeoutError()

    client = TestClient(application)
    response = client.get("/timeout", headers={"X-Request-ID": "database-timeout-1"})

    assert response.status_code == 504
    assert response.json() == {
        "code": "database:timeout",
        "detail": "The database request timed out.",
        "message": "The database request timed out.",
        "requestId": "database-timeout-1",
    }
    assert response.headers["retry-after"] == "1"
    assert response.headers["x-request-id"] == "database-timeout-1"


def test_database_timeout_logs_request_context(monkeypatch, caplog) -> None:
    class TimeoutConnection:
        async def execute(self, _statement: object) -> None:
            raise TimeoutError()

    class TimeoutEngine:
        @asynccontextmanager
        async def connect(self):
            yield TimeoutConnection()

    monkeypatch.setattr(session, "get_engine", TimeoutEngine)

    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    application.add_exception_handler(DatabaseTimeoutError, database_service_error_handler)

    @application.get("/timeout")
    async def raise_timeout() -> None:
        async with get_db_connection() as connection:
            await connection.execute("SELECT 1")

    with caplog.at_level(logging.WARNING, logger=session.__name__):
        response = TestClient(application).get(
            "/timeout",
            headers={"X-Request-ID": "database-log-1"},
        )

    assert response.status_code == 504
    record = next(
        record for record in caplog.records if record.message == "database request failed"
    )
    assert record.database_error_kind == "timeout"
    assert record.database_error_type == "TimeoutError"
    assert record.database_elapsed_ms >= 0
    assert record.request_id == "database-log-1"
    assert record.request_method == "GET"
    assert record.request_path == "/timeout"


def test_database_unavailable_response_has_a_stable_contract() -> None:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    application.add_exception_handler(DatabaseUnavailableError, database_service_error_handler)

    @application.get("/unavailable")
    async def raise_unavailable() -> None:
        raise DatabaseUnavailableError()

    client = TestClient(application)
    response = client.get("/unavailable")

    assert response.status_code == 503
    assert response.json()["code"] == "database:unavailable"
