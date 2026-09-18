import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from app.api.routes import knowledge_files
from app.core.auth import AuthenticatedUser
from app.core.config import Settings


class FakeResult:
    def __init__(self, *, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.scalar_value


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_embed_all_knowledge_file_chunks_processes_current_file_scope(monkeypatch):
    route = next(
        (
            route
            for route in knowledge_files.router.routes
            if route.name == "embed_all_knowledge_file_chunks"
        ),
        None,
    )
    assert route is not None, "the all-chunks embedding route should be registered"

    workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    knowledge_base_id = UUID("00000000-0000-0000-0000-000000000002")
    file_id = UUID("00000000-0000-0000-0000-000000000003")
    chunk_ids = [
        UUID("00000000-0000-0000-0000-000000000004"),
        UUID("00000000-0000-0000-0000-000000000005"),
    ]
    rows = [
        {"chunk_id": chunk_ids[0], "content": "first unembedded chunk"},
        {"chunk_id": chunk_ids[1], "content": "second old-model chunk"},
    ]
    selected_params = []
    saved_params = []

    class Connection:
        async def execute(self, query, params):
            if str(query).lstrip().startswith("SELECT"):
                selected_params.append(params)
                return FakeResult(rows=rows)
            saved_params.append(params)
            return FakeResult(scalar_value=params["chunk_id"])

        def begin(self):
            return FakeTransaction()

    connection = Connection()

    @asynccontextmanager
    async def connection_context():
        yield connection

    permission = []

    async def allow_manage(*args):
        permission.extend(args[1:])

    embedded_texts = []

    async def embed_texts(texts, settings):
        embedded_texts.extend(texts)
        assert settings.embedding_model == "current-model"
        return [[0.25] * 1024, [0.5] * 1024]

    monkeypatch.setattr(knowledge_files, "get_db_connection", connection_context)
    monkeypatch.setattr(
        knowledge_files, "require_knowledge_base_permission", allow_manage
    )
    monkeypatch.setattr(knowledge_files, "embed_texts", embed_texts)

    result = asyncio.run(
        route.endpoint(
            knowledge_base_id=knowledge_base_id,
            file_id=file_id,
            workspace_id=workspace_id,
            current_user=AuthenticatedUser(user_id="chunk-manager"),
            settings=Settings(
                knowledge_ingestion_enabled=True,
                knowledge_embeddings_enabled=True,
                embedding_api_key="test-key",
                embedding_model="current-model",
            ),
        )
    )

    assert result.embedded_count == 2
    assert result.embedding_model == "current-model"
    assert result.dimensions == 1024
    assert embedded_texts == ["first unembedded chunk", "second old-model chunk"]
    assert permission == [workspace_id, knowledge_base_id, "manage"]
    assert selected_params == [
        {
            "file_id": file_id,
            "knowledge_base_id": knowledge_base_id,
            "workspace_id": workspace_id,
            "embedding_model": "current-model",
        }
    ]
    assert [params["chunk_id"] for params in saved_params] == chunk_ids
    assert all(params["file_id"] == file_id for params in saved_params)
    assert all(params["knowledge_base_id"] == knowledge_base_id for params in saved_params)
    assert all(params["workspace_id"] == workspace_id for params in saved_params)
