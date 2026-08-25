from uuid import UUID

from app.api.routes.products import (
    ProductSummary,
    _build_product_search_query,
    _extract_lead_days,
    _normalize_operation_status,
)


def test_normalize_operation_status_keeps_nextjs_aliases() -> None:
    assert _normalize_operation_status("上会调研") == "review"
    assert _normalize_operation_status("已推广") == "promoted"
    assert _normalize_operation_status(" custom ") == "custom"


def test_extract_lead_days_supports_english_and_chinese_units() -> None:
    assert _extract_lead_days("sample 7 days, production 15 天") == 15
    assert _extract_lead_days("ready to ship") is None


def test_product_query_contains_nextjs_advanced_filters() -> None:
    query, params = _build_product_search_query(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        query="charger",
        category="vehicle",
        operation_status="上会调研",
        target_channel="独立站",
        proposer="Alice",
        logistics="FOB",
        qualification="CE",
        source_ids=[UUID("00000000-0000-0000-0000-000000000002")],
    )

    sql = str(query)
    assert 'source."workspaceId" = :workspace_id' in sql
    assert 'research."sourceId" IN' in sql
    assert 'operation."operationStatus" = :operation_status' in sql
    assert params["operation_status"] == "review"
    assert params["source_ids"] == [UUID("00000000-0000-0000-0000-000000000002")]


def test_product_query_can_apply_knowledge_base_grants() -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000002")
    query, params = _build_product_search_query(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        query=None,
        category=None,
        operation_status=None,
        target_channel=None,
        proposer=None,
        logistics=None,
        qualification=None,
        source_ids=[],
        authorized_source_ids=[source_id],
    )

    assert 'source."id" IN' in str(query)
    assert params["authorized_source_ids"] == [source_id]


def test_product_result_exposes_the_shared_citation_contract() -> None:
    citation_schema = ProductSummary.model_json_schema()["properties"]["citation"]

    assert citation_schema["$ref"].endswith("SourceCitation")
