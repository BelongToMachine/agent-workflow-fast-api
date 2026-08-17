from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.config import get_settings


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
    postgres_url = get_settings().postgres_url
    if not postgres_url:
        raise RuntimeError("POSTGRES_URL is not configured for FastAPI.")

    return create_async_engine(
        normalize_postgres_url(postgres_url),
        connect_args={"statement_cache_size": 0},
        pool_pre_ping=True,
    )


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[AsyncConnection]:
    async with get_engine().connect() as connection:
        yield connection
