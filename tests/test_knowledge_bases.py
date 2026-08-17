import asyncio

from fastapi.testclient import TestClient

from app.api.routes.knowledge_bases import (
    KNOWLEDGE_BASE_DELETE,
    KNOWLEDGE_BASE_SELECT,
    KnowledgeBaseWriteRequest,
    _cleanup_knowledge_base_files,
)
from app.core.config import Settings
from app.main import app
from app.services.storage import StorageError

client = TestClient(app)


def test_knowledge_base_name_is_normalized() -> None:
    payload = KnowledgeBaseWriteRequest.model_validate(
        {"displayName": "  Sales Docs  ", "sourceType": " manual "}
    )

    assert payload.display_name == "Sales Docs"
    assert payload.source_type == "manual"


def test_knowledge_base_query_is_workspace_scoped() -> None:
    assert '"workspaceId" = :workspace_id' in str(KNOWLEDGE_BASE_SELECT)
    assert '"workspaceId" = :workspace_id' in str(KNOWLEDGE_BASE_DELETE)


def test_knowledge_base_creation_requires_a_persisted_identity() -> None:
    response = client.post(
        "/api/v1/knowledge-bases",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        json={"displayName": "Sales Docs", "sourceType": "manual"},
    )

    assert response.status_code == 401


def test_knowledge_base_deletion_requires_a_persisted_identity() -> None:
    response = client.delete(
        "/api/v1/knowledge-bases/00000000-0000-0000-0000-000000000002",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401


def test_knowledge_base_storage_cleanup_is_best_effort(monkeypatch) -> None:
    class FakeStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def delete(self, storage_key: str) -> None:
            if storage_key == "broken.pdf":
                raise StorageError("storage unavailable")
            self.deleted.append(storage_key)

    storage = FakeStorage()
    monkeypatch.setattr(
        "app.api.routes.knowledge_bases.get_knowledge_storage_for_provider",
        lambda _settings, _provider: storage,
    )

    failed_count = asyncio.run(
        _cleanup_knowledge_base_files(
            Settings(),
            [
                {"storage_key": "kept.pdf", "storage_provider": "local"},
                {"storage_key": "broken.pdf", "storage_provider": "local"},
            ],
        )
    )

    assert storage.deleted == ["kept.pdf"]
    assert failed_count == 1
