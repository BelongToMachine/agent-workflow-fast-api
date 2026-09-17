from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes.business_data_tables import (
    _build_product_price_queries,
    _parse_filter_model,
    _parse_sort_model,
)
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import WorkspaceAccess
from app.db.business_table_mock import build_product_price_mock_seed
from app.main import app

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
PRICE_ID = UUID("00000000-0000-0000-0000-000000000101")
RESEARCH_ID = UUID("00000000-0000-0000-0000-000000000201")
SOURCE_FILE_ID = UUID("00000000-0000-0000-0000-000000000301")


def test_product_price_queries_scope_search_sort_and_filter_to_workspace() -> None:
    sort = _parse_sort_model('[{"field":"priceMin","direction":"desc"}]')
    filters = _parse_filter_model(
        '{"currency":{"filterType":"text","type":"equals","filter":"USD"},'
        '"priceMin":{"filterType":"number","type":"greaterThanOrEqual",'
        '"filter":"10"}}'
    )

    count_query, rows_query, params = _build_product_price_queries(
        workspace_id=WORKSPACE_ID,
        query="charger",
        sort=sort,
        filters=filters,
        offset=30,
        limit=30,
        authorized_source_ids=[UUID("00000000-0000-0000-0000-000000000401")],
    )

    count_sql = " ".join(str(count_query).split())
    rows_sql = " ".join(str(rows_query).split())
    assert 'source."workspaceId" = :workspace_id' in count_sql
    assert 'research."sourceFileId" = price."sourceFileId"' in count_sql
    assert 'source."knowledgeBaseId" IN' in count_sql
    assert 'CAST(research."productName" AS TEXT) ILIKE :query_pattern' in count_sql
    assert 'price."priceMin" >= :filter_1' in count_sql
    assert 'CAST(price."currency" AS TEXT) ILIKE :filter_0' in count_sql
    assert 'ORDER BY price."priceMin" DESC, price."id" ASC' in rows_sql
    assert "LIMIT :limit OFFSET :offset" in rows_sql
    assert params["query_pattern"] == "%charger%"
    assert params["filter_0"] == "USD"
    assert str(params["filter_1"]) == "10"
    assert params["offset"] == 30
    assert params["limit"] == 30


def test_product_price_sort_and_filter_reject_unregistered_fields() -> None:
    with pytest.raises(HTTPException) as sort_error:
        _parse_sort_model('[{"field":"sourceFileId; DROP TABLE ProductPrice","direction":"asc"}]')
    assert sort_error.value.status_code == 422

    with pytest.raises(HTTPException) as filter_error:
        _parse_filter_model('{"rawText":{"filterType":"text","type":"contains","filter":"x"}}')
    assert filter_error.value.status_code == 422


def test_product_price_sort_appends_stable_id_and_limits_sort_count() -> None:
    assert _parse_sort_model('[{"field":"variant","direction":"asc"}]') == [("variant", "asc")]

    with pytest.raises(HTTPException) as error:
        _parse_sort_model(
            '[{"field":"variant","direction":"asc"},{"field":"currency","direction":"desc"}]'
        )
    assert error.value.status_code == 422


def test_product_price_rows_endpoint_returns_paged_database_response(monkeypatch) -> None:
    class FakeMappings:
        def __init__(self, rows):
            self.rows = rows

        def one(self):
            return self.rows[0]

        def all(self):
            return self.rows

    class FakeResult:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return FakeMappings(self.rows)

    class FakeConnection:
        async def execute(self, query, params):
            sql = str(query)
            calls.append((sql, params))
            if "COUNT(*) AS total" in sql:
                return FakeResult([{"total": 1}])
            return FakeResult(
                [
                    {
                        "id": PRICE_ID,
                        "researchId": RESEARCH_ID,
                        "productName": "Demo charger",
                        "category": "Electronics",
                        "brand": "Northstar",
                        "sourceFileId": SOURCE_FILE_ID,
                        "sourceFileName": "Product pricing mock.csv",
                        "variant": "USB-C 65W",
                        "priceMin": "12.50",
                        "priceMax": "15.00",
                        "currency": "USD",
                        "priceType": "mock_quote",
                        "sourceSheet": "Product Pricing",
                        "sourceRow": 2,
                    }
                ]
            )

    @asynccontextmanager
    async def fake_db_connection():
        yield FakeConnection()

    async def fake_workspace_permission(*args, **kwargs):
        return WorkspaceAccess(
            user_id="test-user",
            workspace_id=WORKSPACE_ID,
            role="owner",
            permissions=["knowledge.manage"],
            is_guest=False,
            is_development=True,
        )

    async def no_source_restrictions(*args, **kwargs):
        return None

    calls = []
    monkeypatch.setattr(
        "app.api.routes.business_data_tables.get_db_connection",
        fake_db_connection,
    )
    monkeypatch.setattr(
        "app.api.routes.business_data_tables.require_workspace_permission",
        fake_workspace_permission,
    )
    monkeypatch.setattr(
        "app.api.routes.business_data_tables.get_authorized_source_ids",
        no_source_restrictions,
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id="test-user",
        workspace_id=str(WORKSPACE_ID),
        is_development=True,
    )

    try:
        response = TestClient(app).get(
            "/api/v1/admin/data-tables/ProductPrice/rows",
            params={"workspace_id": str(WORKSPACE_ID), "offset": 0, "limit": 30},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["hasMore"] is False
    assert payload["rows"][0]["researchId"] == str(RESEARCH_ID)
    assert payload["rows"][0]["productName"] == "Demo charger"
    assert len(calls) == 2
    assert all(call_params["workspace_id"] == str(WORKSPACE_ID) for _, call_params in calls)


def test_product_price_rows_endpoint_caps_infinite_block_size() -> None:
    response = TestClient(app).get(
        "/api/v1/admin/data-tables/ProductPrice/rows",
        params={"workspace_id": str(WORKSPACE_ID), "offset": 0, "limit": 501},
    )

    assert response.status_code == 422


def test_product_price_mock_seed_contains_only_pricing_and_required_product_parents() -> None:
    knowledge_base_id = UUID("00000000-0000-0000-0000-000000000501")
    source, sections = build_product_price_mock_seed(WORKSPACE_ID, knowledge_base_id)

    assert source.knowledge_base_id == knowledge_base_id
    assert source.display_name == "Mock Product Pricing Demo.csv"
    assert set(sections) == {"realProductResearch", "productPrices"}
    assert len(sections["realProductResearch"]) == 18
    assert len(sections["productPrices"]) == 54
    research_ids = {row["id"] for row in sections["realProductResearch"]}
    assert {row["researchId"] for row in sections["productPrices"]} == research_ids
    assert all(isinstance(row["priceMin"], Decimal) for row in sections["productPrices"])
    assert all(row["priceType"] == "mock_quote" for row in sections["productPrices"])


def test_product_price_mock_seed_is_stable_across_runs() -> None:
    first = build_product_price_mock_seed(WORKSPACE_ID, SOURCE_FILE_ID)
    second = build_product_price_mock_seed(WORKSPACE_ID, SOURCE_FILE_ID)

    assert first == second
