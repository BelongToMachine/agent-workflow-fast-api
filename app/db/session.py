import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from time import monotonic

from asyncpg.exceptions import (
    CannotConnectNowError,
    PostgresConnectionError,
    QueryCanceledError,
    TooManyConnectionsError,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.config import get_settings
from app.core.request_context import get_request_context
from app.db.errors import DatabaseServiceError, DatabaseTimeoutError, DatabaseUnavailableError

logger = logging.getLogger(__name__)


def normalize_postgres_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    postgres_url = settings.postgres_url
    if not postgres_url:
        raise DatabaseUnavailableError()

    return create_async_engine(
        normalize_postgres_url(postgres_url),
        connect_args={
            "command_timeout": settings.postgres_command_timeout_seconds,
            "statement_cache_size": 0,
            "timeout": settings.postgres_connect_timeout_seconds,
        },
        pool_pre_ping=True,
        pool_timeout=settings.postgres_pool_timeout_seconds,
    )


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[AsyncConnection]:
    started_at = monotonic()
    try:
        async with get_engine().connect() as connection:
            yield connection
    except DatabaseServiceError:
        raise
    except (TimeoutError, SQLAlchemyTimeoutError, QueryCanceledError) as error:
        _log_database_failure("timeout", error, started_at)
        raise DatabaseTimeoutError() from error
    except (
        OSError,
        CannotConnectNowError,
        PostgresConnectionError,
        TooManyConnectionsError,
    ) as error:
        _log_database_failure("unavailable", error, started_at)
        raise DatabaseUnavailableError() from error
    except DBAPIError as error:
        if _is_query_timeout(error):
            _log_database_failure("timeout", error, started_at)
            raise DatabaseTimeoutError() from error
        if error.connection_invalidated:
            _log_database_failure("unavailable", error, started_at)
            raise DatabaseUnavailableError() from error
        raise


def _is_query_timeout(error: DBAPIError) -> bool:
    """Recognize PostgreSQL's query-cancel SQLSTATE through SQLAlchemy."""
    candidate: BaseException | None = error
    for _ in range(3):
        if candidate is None:
            return False
        if getattr(candidate, "sqlstate", None) == "57014":
            return True
        original = getattr(candidate, "orig", None)
        candidate = original if isinstance(original, BaseException) else candidate.__cause__
    return False


def _log_database_failure(
    kind: str,
    error: BaseException,
    started_at: float,
) -> None:
    context = get_request_context()
    logger.warning(
        "database request failed",
        extra={
            "database_error_kind": kind,
            "database_error_type": type(error).__name__,
            "database_elapsed_ms": round((monotonic() - started_at) * 1000),
            "request_id": context.request_id if context else None,
            "request_method": context.method if context else None,
            "request_path": context.path if context else None,
        },
    )
