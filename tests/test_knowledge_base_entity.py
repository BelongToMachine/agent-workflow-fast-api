from app.api.routes.admin_knowledge_grants import (
    grant_knowledge_base_query,
    grants_select_query,
)
from app.api.routes.content import _build_content_search_query
from app.api.routes.content import source_names_query as content_source_names_query
from app.api.routes.knowledge_bases import (
    knowledge_base_delete_query,
    knowledge_base_insert_query,
    knowledge_base_select_query,
    knowledge_base_update_query,
)
from app.api.routes.knowledge_sources import _build_knowledge_sources_query
from app.api.routes.products import _build_product_search_query, source_names_query
from app.core.config import get_settings
from app.core.knowledge_access import (
    AUTHORIZED_SOURCE_IDS_QUERY_TEMPLATE,
    KNOWLEDGE_BASE_ACCESS_QUERY_TEMPLATE,
    KNOWLEDGE_BASE_EXISTS_QUERY_TEMPLATE,
)
from app.core.knowledge_base_entity import (
    render_knowledge_base_query,
)
from app.db.migrate_knowledge_bases import MIGRATION_PATH


def test_legacy_environment_flag_cannot_select_knowledge_source(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_ENTITY_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert 'FROM "KnowledgeBase"' in str(knowledge_base_select_query())
        assert 'INSERT INTO "KnowledgeBase"' in str(knowledge_base_insert_query())
        assert 'UPDATE "KnowledgeBase"' in str(knowledge_base_update_query())
        assert 'DELETE FROM "KnowledgeBase"' in str(knowledge_base_delete_query())
    finally:
        get_settings.cache_clear()


def test_knowledge_queries_share_the_independent_entity() -> None:
    workspace_id = "00000000-0000-0000-0000-000000000001"

    assert 'FROM "KnowledgeBase"' in str(
        render_knowledge_base_query(AUTHORIZED_SOURCE_IDS_QUERY_TEMPLATE)
    )
    assert 'FROM "KnowledgeBase"' in str(
        render_knowledge_base_query(KNOWLEDGE_BASE_ACCESS_QUERY_TEMPLATE)
    )
    assert 'FROM "KnowledgeBase"' in str(
        render_knowledge_base_query(KNOWLEDGE_BASE_EXISTS_QUERY_TEMPLATE)
    )
    assert 'INNER JOIN "KnowledgeBase"' in str(grants_select_query())
    assert 'FROM "KnowledgeBase"' in str(grant_knowledge_base_query())

    source_query, source_params = _build_knowledge_sources_query(
        workspace_id,
        None,
    )
    assert 'FROM "KnowledgeFile"' in str(source_query)
    assert source_params["workspace_id"] == workspace_id

    product_query, _ = _build_product_search_query(
        workspace_id=workspace_id,
        query=None,
        category=None,
        operation_status=None,
        target_channel=None,
        proposer=None,
        logistics=None,
        qualification=None,
        source_ids=[],
    )
    assert '"KnowledgeFile" AS source' in str(product_query)
    assert 'FROM "KnowledgeFile"' in str(source_names_query())

    content_query, _ = _build_content_search_query(
        workspace_id=workspace_id,
        account=None,
        language=None,
        product=None,
        query=None,
        record_type=None,
        status=None,
        submitter=None,
        source_ids=[],
        limit=10,
    )
    assert '"KnowledgeFile" AS source' in str(content_query)
    assert 'FROM "KnowledgeFile"' in str(content_source_names_query())


def test_knowledge_base_migration_backfills_and_repoints_dependencies() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'CREATE TABLE IF NOT EXISTS "KnowledgeBase"' in sql
    assert 'FROM "KnowledgeSource" AS source' in sql
    assert 'ON CONFLICT ("id") DO NOTHING' in sql
    assert "KnowledgeBaseGrant_knowledge_base_entity_fk" in sql
    assert "KnowledgeFile_knowledge_base_entity_fk" in sql
    assert "KnowledgeChunk_knowledge_base_entity_fk" in sql
