import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.migration_status import MIGRATION_STATUS_QUERY, build_migration_statuses
from app.db.migration_utils import get_migration_target
from app.db.session import normalize_postgres_url
from app.services.embeddings import embed_texts
from app.services.resumable_streams import ResumableStreamStore
from app.services.storage import S3KnowledgeStorage

pytestmark = pytest.mark.integration


def _configured_url(environment_variable: str) -> str:
    value = os.getenv(environment_variable)
    if not value:
        pytest.skip(f"Set {environment_variable} to run infrastructure integration tests.")
    return value


def _configured_value(environment_variable: str) -> str:
    value = os.getenv(environment_variable)
    if not value:
        pytest.skip(f"Set {environment_variable} to run infrastructure integration tests.")
    return value


def _assert_safe_target(url: str, environment_variable: str) -> None:
    host = urlparse(url).hostname
    if host in {None, "localhost", "127.0.0.1", "::1", "minio", "postgres", "redis"}:
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


async def _redis_stream_round_trip(redis_url: str) -> None:
    client = Redis.from_url(redis_url, decode_responses=True)
    store = ResumableStreamStore(redis_url, 30, client=client)
    chat_id = f"integration-chat-{uuid4()}"
    stream_id: str | None = None

    async def source():
        yield "data: first\n\n"
        yield "data: second\n\n"

    try:
        captured = [chunk async for chunk in store.capture(chat_id, source())]
        stream_id = await store.active_stream_id(chat_id)
        assert stream_id is not None
        resumed = [chunk async for chunk in store.resume(chat_id, stream_id)]
        assert resumed == captured
    finally:
        if stream_id:
            await client.delete(
                store._active_key(chat_id),
                store._chunks_key(stream_id),
                store._done_key(stream_id),
            )
        await client.aclose()


def test_local_redis_replays_a_completed_stream() -> None:
    redis_url = _configured_url("FASTAPI_TEST_REDIS_URL")
    _assert_safe_target(redis_url, "FASTAPI_TEST_REDIS_URL")

    asyncio.run(_redis_stream_round_trip(redis_url))


def test_postgres_target_parser_matches_the_explicit_integration_url() -> None:
    postgres_url = _configured_url("FASTAPI_TEST_POSTGRES_URL")
    target = get_migration_target(Settings(postgres_url=postgres_url))

    assert target.database
    assert target.display_name


async def _s3_round_trip(
    *,
    endpoint_url: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
) -> None:
    storage = S3KnowledgeStorage(
        access_key_id=access_key_id,
        bucket=bucket,
        endpoint_url=endpoint_url,
        region=region,
        secret_access_key=secret_access_key,
    )
    storage_key = f"asianode:test:integration/{uuid4()}.txt"
    content = b"asianode storage integration"
    await storage.put(storage_key, content)
    try:
        assert await storage.read(storage_key) == content
        signed_url = await storage.presigned_url(storage_key, 60)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(signed_url)
        response.raise_for_status()
        assert response.content == content
    finally:
        await storage.delete(storage_key)


def test_s3_compatible_storage_supports_upload_read_and_presigned_download() -> None:
    endpoint_url = _configured_url("FASTAPI_TEST_S3_ENDPOINT_URL")
    _assert_safe_target(endpoint_url, "FASTAPI_TEST_S3_ENDPOINT_URL")

    asyncio.run(
        _s3_round_trip(
            access_key_id=_configured_value("FASTAPI_TEST_S3_ACCESS_KEY_ID"),
            bucket=_configured_value("FASTAPI_TEST_S3_BUCKET"),
            endpoint_url=endpoint_url,
            region=os.getenv("FASTAPI_TEST_S3_REGION", "us-east-1"),
            secret_access_key=_configured_value("FASTAPI_TEST_S3_SECRET_ACCESS_KEY"),
        )
    )


def test_embedding_provider_returns_valid_vectors() -> None:
    base_url = _configured_url("FASTAPI_TEST_EMBEDDING_BASE_URL")
    _assert_safe_target(base_url, "FASTAPI_TEST_EMBEDDING_BASE_URL")

    settings = Settings(
        embedding_api_key=_configured_value("FASTAPI_TEST_EMBEDDING_API_KEY"),
        embedding_base_url=base_url,
        embedding_model=os.getenv("FASTAPI_TEST_EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_provider_timeout_seconds=float(
            os.getenv("FASTAPI_TEST_EMBEDDING_TIMEOUT_SECONDS", "60")
        ),
    )
    vectors = asyncio.run(embed_texts(["Asianode embedding integration probe"], settings))

    assert len(vectors) == 1
    assert len(vectors[0]) == 1536
