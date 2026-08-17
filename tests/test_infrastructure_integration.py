import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.migration_status import MIGRATION_STATUS_QUERY, build_migration_statuses
from app.db.migration_utils import get_migration_target
from app.db.session import normalize_postgres_url

pytestmark = pytest.mark.integration


def _configured_url(environment_variable: str) -> str:
    value = os.getenv(environment_variable)
    if not value:
        pytest.skip(f"Set {environment_variable} to run infrastructure integration tests.")
    return value


def _assert_safe_target(url: str, environment_variable: str) -> None:
    host = urlparse(url).hostname
    if host in {None, "localhost", "127.0.0.1", "::1", "postgres", "redis"}:
        return
    if os.getenv("FASTAPI_ALLOW_REMOTE_INTEGRATION") != "1":
        pytest.fail(
            f"{environment_variable} points to remote host {host!r}; "
            "set FASTAPI_ALLOW_REMOTE_INTEGRATION=1 only after explicit review."
        )


async def _read_migration_status(postgres_url: str) -> dict[str, object]:
    engine = create_async_engine(
        normalize_postgres_url(postgres_url),
        connect_args={"statement_cache_size": 0},
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as connection:
            result = await connection.execute(MIGRATION_STATUS_QUERY)
            return dict(result.mappings().one())
    finally:
        await engine.dispose()


def test_local_postgres_has_all_knowledge_migrations_applied() -> None:
    postgres_url = _configured_url("FASTAPI_TEST_POSTGRES_URL")
    _assert_safe_target(postgres_url, "FASTAPI_TEST_POSTGRES_URL")

    row = asyncio.run(_read_migration_status(postgres_url))
    statuses = build_migration_statuses(row)

    assert all(status.applied for status in statuses), [
        status.name for status in statuses if not status.applied
    ]


async def _redis_round_trip(redis_url: str) -> None:
    client = Redis.from_url(redis_url, decode_responses=True)
    key = f"asianode:test:integration:{uuid4()}"
    try:
        assert await client.ping() is True
        assert await client.set(key, "ok", ex=30) is True
        assert await client.get(key) == "ok"
    finally:
        await client.delete(key)
        await client.aclose()


def test_local_redis_supports_resumable_stream_storage() -> None:
    redis_url = _configured_url("FASTAPI_TEST_REDIS_URL")
    _assert_safe_target(redis_url, "FASTAPI_TEST_REDIS_URL")

    asyncio.run(_redis_round_trip(redis_url))


def test_postgres_target_parser_matches_the_explicit_integration_url() -> None:
    postgres_url = _configured_url("FASTAPI_TEST_POSTGRES_URL")
    target = get_migration_target(Settings(postgres_url=postgres_url))

    assert target.database
    assert target.display_name
