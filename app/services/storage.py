import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings


class StorageConfigurationError(Exception):
    """Raised when an object storage backend is configured incompletely."""


class StorageError(Exception):
    """Raised when an object cannot be written, read, or deleted."""


class LocalKnowledgeStorage:
    provider = "local"

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def path_for(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()
        if self.root != path and self.root not in path.parents:
            raise StorageError("Invalid knowledge file storage key.")
        return path

    async def put(self, storage_key: str, content: bytes) -> None:
        path = self.path_for(storage_key)
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, content)
        except OSError as error:
            raise StorageError("The local knowledge storage could not write the file.") from error

    async def read(self, storage_key: str) -> bytes:
        try:
            return await asyncio.to_thread(self.path_for(storage_key).read_bytes)
        except OSError as error:
            raise StorageError("The local knowledge storage could not read the file.") from error

    async def delete(self, storage_key: str) -> None:
        try:
            await asyncio.to_thread(self.path_for(storage_key).unlink, missing_ok=True)
        except OSError as error:
            raise StorageError("The local knowledge storage could not delete the file.") from error


class S3KnowledgeStorage:
    provider = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        if client is not None:
            self._client = client
            return
        try:
            self._client = boto3.client(
                "s3",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                endpoint_url=endpoint_url,
                region_name=region,
            )
        except (BotoCoreError, ClientError) as error:
            raise StorageConfigurationError(
                "The S3 knowledge storage client could not be configured."
            ) from error

    async def put(self, storage_key: str, content: bytes) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.bucket,
                Body=content,
                Key=storage_key,
            )
        except (BotoCoreError, ClientError) as error:
            raise StorageError("The S3 knowledge storage could not write the file.") from error

    async def read(self, storage_key: str) -> bytes:
        def read_object() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=storage_key)
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()

        try:
            return await asyncio.to_thread(read_object)
        except (BotoCoreError, ClientError, KeyError) as error:
            raise StorageError("The S3 knowledge storage could not read the file.") from error

    async def delete(self, storage_key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self.bucket,
                Key=storage_key,
            )
        except (BotoCoreError, ClientError) as error:
            raise StorageError("The S3 knowledge storage could not delete the file.") from error


def build_knowledge_storage(settings: Settings) -> LocalKnowledgeStorage | S3KnowledgeStorage:
    if settings.knowledge_storage_provider == "local":
        return LocalKnowledgeStorage(settings.knowledge_storage_dir)
    if settings.knowledge_storage_provider == "s3":
        if not settings.knowledge_s3_bucket:
            raise StorageConfigurationError(
                "KNOWLEDGE_S3_BUCKET is required when KNOWLEDGE_STORAGE_PROVIDER=s3."
            )
        return S3KnowledgeStorage(
            access_key_id=settings.knowledge_s3_access_key_id,
            bucket=settings.knowledge_s3_bucket,
            endpoint_url=settings.knowledge_s3_endpoint_url,
            region=settings.knowledge_s3_region,
            secret_access_key=settings.knowledge_s3_secret_access_key,
        )
    raise StorageConfigurationError(
        "KNOWLEDGE_STORAGE_PROVIDER must be either local or s3."
    )


@lru_cache(maxsize=8)
def _cached_knowledge_storage(
    provider: str,
    storage_dir: str,
    bucket: str | None,
    endpoint_url: str | None,
    region: str,
    access_key_id: str | None,
    secret_access_key: str | None,
) -> LocalKnowledgeStorage | S3KnowledgeStorage:
    settings = Settings(
        knowledge_s3_access_key_id=access_key_id,
        knowledge_s3_bucket=bucket,
        knowledge_s3_endpoint_url=endpoint_url,
        knowledge_s3_region=region,
        knowledge_s3_secret_access_key=secret_access_key,
        knowledge_storage_dir=storage_dir,
        knowledge_storage_provider=provider,
    )
    return build_knowledge_storage(settings)


def get_knowledge_storage(settings: Settings) -> LocalKnowledgeStorage | S3KnowledgeStorage:
    return _cached_knowledge_storage(
        settings.knowledge_storage_provider,
        settings.knowledge_storage_dir,
        settings.knowledge_s3_bucket,
        settings.knowledge_s3_endpoint_url,
        settings.knowledge_s3_region,
        settings.knowledge_s3_access_key_id,
        settings.knowledge_s3_secret_access_key,
    )


def get_knowledge_storage_for_provider(
    settings: Settings,
    provider: str,
) -> LocalKnowledgeStorage | S3KnowledgeStorage:
    if provider == settings.knowledge_storage_provider:
        return get_knowledge_storage(settings)
    return build_knowledge_storage(
        settings.model_copy(update={"knowledge_storage_provider": provider})
    )
