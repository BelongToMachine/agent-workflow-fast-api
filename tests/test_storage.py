import asyncio

import pytest

from app.core.config import Settings
from app.services.storage import (
    LocalKnowledgeStorage,
    S3KnowledgeStorage,
    StorageConfigurationError,
    StorageError,
    build_knowledge_storage,
)


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        self.closed = True


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Body: bytes, Key: str) -> None:
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, FakeBody]:
        return {"Body": FakeBody(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)


def test_local_storage_round_trip_and_path_sandbox(tmp_path) -> None:
    storage = LocalKnowledgeStorage(str(tmp_path))

    asyncio.run(storage.put("workspace/file.txt", b"hello"))
    assert asyncio.run(storage.read("workspace/file.txt")) == b"hello"
    asyncio.run(storage.delete("workspace/file.txt"))

    with pytest.raises(StorageError):
        storage.path_for("../../outside.txt")


def test_s3_storage_round_trip() -> None:
    client = FakeS3Client()
    storage = S3KnowledgeStorage(
        access_key_id=None,
        bucket="knowledge",
        client=client,
        endpoint_url="http://localhost:9000",
        region="us-east-1",
        secret_access_key=None,
    )

    asyncio.run(storage.put("workspace/file.txt", b"hello"))
    assert asyncio.run(storage.read("workspace/file.txt")) == b"hello"
    asyncio.run(storage.delete("workspace/file.txt"))
    assert client.objects == {}


def test_s3_storage_requires_a_bucket() -> None:
    with pytest.raises(StorageConfigurationError):
        build_knowledge_storage(Settings(knowledge_storage_provider="s3"))
