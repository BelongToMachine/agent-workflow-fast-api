import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.knowledge_access import get_authorized_source_ids
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(tags=["products"])


class ProductSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: str = Field(alias="productId")
    sku: str | None = None
    name_en: str = Field(alias="nameEn")
    name_zh: str | None = Field(default=None, alias="nameZh")
    name_tr: str | None = Field(default=None, alias="nameTr")
    category: str = "未分类"
    material: str | None = None
    unit_price_usd: str | None = Field(default=None, alias="unitPriceUsd")
    moq_units: int | None = Field(default=None, alias="moqUnits")
    lead_time_days: float | None = Field(default=None, alias="leadTimeDays")
    customization: str | None = None
    sample_available: bool | None = Field(default=None, alias="sampleAvailable")
    supplier_id: str | None = Field(default=None, alias="supplierId")
    supplier_name: str = Field(default="未提供", alias="supplierName")
    supplier_city: str | None = Field(default=None, alias="supplierCity")
    supplier_quality_rating: str | None = Field(default=None, alias="supplierQualityRating")
    price_min: str | None = Field(default=None, alias="priceMin")
    price_max: str | None = Field(default=None, alias="priceMax")
    price_currency: str | None = Field(default=None, alias="priceCurrency")
    price_summary: str | None = Field(default=None, alias="priceSummary")
    operation_status: str | None = Field(default=None, alias="operationStatus")
    promotion_status: str | None = Field(default=None, alias="promotionStatus")
    proposer: str | None = None
    logistics_term: str | None = Field(default=None, alias="logisticsTerm")
    qualifications: str | None = None
    has_documents: bool = Field(default=False, alias="hasDocuments")
    document_count: int = Field(default=0, alias="documentCount")
    source_id: str | None = Field(default=None, alias="sourceId")
    source_file_name: str | None = Field(default=None, alias="sourceFileName")
    source_sheet: str | None = Field(default=None, alias="sourceSheet")
    source_row: int | None = Field(default=None, alias="sourceRow")


class ProductSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    products: list[ProductSummary]
    source: str = "enterprise"
    source_table: str = Field(default="RealProductResearch + operations", alias="sourceTable")
    message: str | None = None


OPERATION_STATUS_ALIASES = {
    "上会调研": "review",
    "否": "not_promoted",
    "已推广": "promoted",
    "是": "promoted",
    "未推广": "not_promoted",
    "调研": "review",
}

PRODUCT_SEARCH_SELECT = """
    SELECT
        research."id" AS research_id,
        research."category" AS category,
        research."contactPerson" AS contact_person,
        research."procurementConditions" AS procurement_conditions,
        research."brand" AS product_brand,
        research."productFeatures" AS product_features,
        research."productHighlights" AS product_highlights,
        research."productIntro" AS product_intro,
        research."productName" AS product_name,
        research."shippingTime" AS shipping_time,
        research."sourceId" AS source_id,
        research."sourceSheet" AS source_sheet,
        research."sourceRow" AS source_row,
        research."supplierContact" AS supplier_contact,
        operation."logisticsTerm" AS logistics_term,
        operation."operationStatus" AS operation_status,
        operation."promotionStatus" AS promotion_status,
        operation."proposer" AS proposer,
        operation."qualifications" AS qualifications,
        operation."targetChannels" AS target_channels,
        source."displayName" AS source_file_name
    FROM "RealProductResearch" AS research
    INNER JOIN "KnowledgeSource" AS source
        ON source."id" = research."sourceId"
    LEFT JOIN "ProductOperation" AS operation
        ON operation."researchId" = research."id"
    WHERE {conditions}
    ORDER BY research."productName" ASC
"""

SOURCE_NAMES_QUERY = text(
    """
    SELECT
        "displayName" AS display_name,
        "id" AS source_id
    FROM "KnowledgeSource"
    WHERE "workspaceId" = :workspace_id
      AND "status" = 'ready'
      AND "displayName" IN :source_file_names
    """
).bindparams(bindparam("source_file_names", expanding=True))

PRODUCT_PRICES_QUERY = text(
    """
    SELECT
        "researchId" AS research_id,
        "currency" AS currency,
        "priceMax" AS price_max,
        "priceMin" AS price_min,
        "variant" AS variant
    FROM "ProductPrice"
    WHERE "researchId" IN :research_ids
    """
).bindparams(bindparam("research_ids", expanding=True))

PRODUCT_DOCUMENTS_QUERY = text(
    """
    SELECT "researchId" AS research_id
    FROM "ProductDocument"
    WHERE "researchId" IN :research_ids
    """
).bindparams(bindparam("research_ids", expanding=True))


def _pattern(value: str | None) -> str | None:
    return f"%{value.strip()}%" if value and value.strip() else None


def _normalized_values(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values or [] if value.strip()))


def _normalize_operation_status(value: str) -> str:
    normalized = value.strip().lower()
    return OPERATION_STATUS_ALIASES.get(normalized, normalized)


def _extract_lead_days(value: str | None) -> float | None:
    if not value:
        return None

    days = [
        float(match.group(1))
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:days?|日|天)", value, re.I)
    ]
    return max(days) if days else None


def _string_value(value: object) -> str | None:
    return None if value is None else str(value)


def _number_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_product_search_query(
    *,
    workspace_id: UUID,
    query: str | None,
    category: str | None,
    operation_status: str | None,
    target_channel: str | None,
    proposer: str | None,
    logistics: str | None,
    qualification: str | None,
    source_file_names: list[str],
    authorized_source_ids: list[UUID] | None = None,
) -> tuple[object, dict[str, object]]:
    conditions = [
        'source."workspaceId" = :workspace_id',
        "source.\"status\" = 'ready'",
    ]
    params: dict[str, object] = {"workspace_id": str(workspace_id)}

    query_pattern = _pattern(query)
    if query_pattern:
        conditions.append(
            "("
            'research."productName" ILIKE :query_pattern '
            'OR research."category" ILIKE :query_pattern '
            'OR research."productHighlights" ILIKE :query_pattern '
            'OR research."productFeatures" ILIKE :query_pattern '
            'OR research."productIntro" ILIKE :query_pattern '
            'OR research."procurementConditions" ILIKE :query_pattern '
            'OR research."brand" ILIKE :query_pattern'
            ")"
        )
        params["query_pattern"] = query_pattern

    text_filters = {
        'research."category"': ("category", category),
        'operation."logisticsTerm"': ("logistics", logistics),
        'operation."proposer"': ("proposer", proposer),
        'operation."qualifications"': ("qualification", qualification),
        'operation."targetChannels"': ("target_channel", target_channel),
    }
    for column, (parameter_name, value) in text_filters.items():
        pattern = _pattern(value)
        if pattern:
            bind_name = f"{parameter_name}_pattern"
            conditions.append(f"{column} ILIKE :{bind_name}")
            params[bind_name] = pattern

    if operation_status and operation_status.strip():
        conditions.append('operation."operationStatus" = :operation_status')
        params["operation_status"] = _normalize_operation_status(operation_status)

    if source_file_names:
        conditions.append('source."displayName" IN :source_file_names')
        params["source_file_names"] = source_file_names

    if authorized_source_ids is not None:
        conditions.append('source."id" IN :authorized_source_ids')
        params["authorized_source_ids"] = authorized_source_ids

    query_text = text(PRODUCT_SEARCH_SELECT.format(conditions=" AND ".join(conditions)))
    bind_params = []
    if source_file_names:
        bind_params.append(bindparam("source_file_names", expanding=True))
    if authorized_source_ids is not None:
        bind_params.append(bindparam("authorized_source_ids", expanding=True))
    if bind_params:
        query_text = query_text.bindparams(*bind_params)
    return query_text, params


def _empty_response(message: str | None = None) -> ProductSearchResponse:
    return ProductSearchResponse(products=[], message=message)


def _format_price(price: dict[str, object]) -> str:
    minimum = _string_value(price["price_min"]) or ""
    maximum = _string_value(price["price_max"])
    maximum_suffix = f"-{maximum}" if maximum else ""
    return f"{price['variant']}: {price['currency']} {minimum}{maximum_suffix}"


@router.get("/products", response_model=ProductSearchResponse)
async def search_products(
    _current_user: AuthenticatedUser = Depends(get_current_user),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    query: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=100),
    max_price_usd: float | None = Query(default=None, alias="maxPriceUsd", ge=0),
    max_lead_days: float | None = Query(default=None, alias="maxLeadDays", ge=0),
    max_moq_units: int | None = Query(default=None, alias="maxMoqUnits", ge=0),
    operation_status: str | None = Query(default=None, alias="operationStatus", max_length=100),
    target_channel: str | None = Query(default=None, alias="targetChannel", max_length=200),
    proposer: str | None = Query(default=None, max_length=100),
    logistics: str | None = Query(default=None, max_length=100),
    qualification: str | None = Query(default=None, max_length=200),
    has_document: bool | None = Query(default=None, alias="hasDocument"),
    missing_field: Literal["price", "supplier", "qualification", "document", "promotionStatus"]
    | None = Query(default=None, alias="missingField"),
    limit: int = Query(default=10, ge=1, le=50),
    source_file_names: list[str] | None = Query(
        default=None, alias="sourceFileNames", max_length=50
    ),
) -> ProductSearchResponse | JSONResponse:
    workspace_access = await require_workspace_permission(
        _current_user,
        workspace_id,
        "knowledge.read",
    )
    authorized_source_ids = await get_authorized_source_ids(
        _current_user,
        workspace_id,
        is_guest=workspace_access.is_guest,
        workspace_role=workspace_access.role,
    )
    if authorized_source_ids == []:
        return _empty_response("No knowledge source is authorized for this account.")
    normalized_source_file_names = _normalized_values(source_file_names)

    try:
        async with get_db_connection() as connection:
            missing_source_file_names: list[str] = []
            if normalized_source_file_names:
                source_result = await connection.execute(
                    SOURCE_NAMES_QUERY,
                    {
                        "source_file_names": normalized_source_file_names,
                        "workspace_id": str(workspace_id),
                    },
                )
                source_rows = source_result.mappings().all()
                if authorized_source_ids is not None:
                    authorized_source_id_set = set(authorized_source_ids)
                    source_rows = [
                        row
                        for row in source_rows
                        if row["source_id"] in authorized_source_id_set
                    ]
                found_source_names = {row["display_name"] for row in source_rows}
                missing_source_file_names = [
                    name for name in normalized_source_file_names if name not in found_source_names
                ]
                if not found_source_names:
                    return _empty_response(
                        "No knowledge source matched: " + ", ".join(normalized_source_file_names)
                    )

            if max_moq_units is not None:
                return _empty_response(
                    "The enterprise dataset does not contain a structured MOQ field, "
                    "so the MOQ filter was not applied and no products were returned."
                )

            search_query, params = _build_product_search_query(
                workspace_id=workspace_id,
                query=query,
                category=category,
                operation_status=operation_status,
                target_channel=target_channel,
                proposer=proposer,
                logistics=logistics,
                qualification=qualification,
                source_file_names=normalized_source_file_names,
                authorized_source_ids=authorized_source_ids,
            )
            result = await connection.execute(search_query, params)
            rows = result.mappings().all()

            research_ids = [row["research_id"] for row in rows]
            price_rows = []
            document_rows = []
            if research_ids:
                price_result = await connection.execute(
                    PRODUCT_PRICES_QUERY, {"research_ids": research_ids}
                )
                document_result = await connection.execute(
                    PRODUCT_DOCUMENTS_QUERY, {"research_ids": research_ids}
                )
                price_rows = price_result.mappings().all()
                document_rows = document_result.mappings().all()
    except RuntimeError as error:
        return JSONResponse(
            status_code=503,
            content={"code": "database:unavailable", "cause": str(error)},
        )
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={
                "code": "database:unavailable",
                "cause": "FastAPI could not query the PostgreSQL database.",
            },
        )

    prices_by_research_id: dict[UUID, list[dict[str, object]]] = {}
    for price in price_rows:
        prices_by_research_id.setdefault(price["research_id"], []).append(price)

    document_count_by_research_id: dict[UUID, int] = {}
    for document in document_rows:
        research_id = document["research_id"]
        document_count_by_research_id[research_id] = (
            document_count_by_research_id.get(research_id, 0) + 1
        )

    products: list[tuple[float, str, ProductSummary]] = []
    for row in rows:
        research_id = row["research_id"]
        prices = prices_by_research_id.get(research_id, [])
        document_count = document_count_by_research_id.get(research_id, 0)
        lead_time_days = _extract_lead_days(row["shipping_time"])
        usd_prices = [
            number
            for price in prices
            if price["currency"] == "USD"
            for number in (
                _number_value(price["price_min"]),
                _number_value(price["price_max"]),
            )
            if number is not None
        ]

        if max_price_usd is not None and (not usd_prices or min(usd_prices) > max_price_usd):
            continue
        if max_lead_days is not None and (lead_time_days is None or lead_time_days > max_lead_days):
            continue
        if has_document is not None and (document_count > 0) != has_document:
            continue
        if missing_field == "price" and prices:
            continue
        if missing_field == "supplier" and (row["contact_person"] or row["supplier_contact"]):
            continue
        if missing_field == "qualification" and row["qualifications"]:
            continue
        if missing_field == "document" and document_count > 0:
            continue
        if missing_field == "promotionStatus" and row["promotion_status"]:
            continue

        price = prices[0] if prices else None
        unit_price_usd = next(
            (price["price_min"] for price in prices if price["currency"] == "USD"),
            None,
        )
        price_summary = "; ".join(_format_price(item) for item in prices[:8]) if prices else None
        product = ProductSummary(
            productId=f"REAL-{row['source_sheet']}-{row['source_row']}",
            sku=None,
            nameEn=row["product_name"],
            nameZh=row["product_name"],
            nameTr=None,
            category=row["category"] or "未分类",
            material=row["product_features"],
            unitPriceUsd=_string_value(unit_price_usd),
            moqUnits=None,
            leadTimeDays=lead_time_days,
            customization=row["procurement_conditions"],
            sampleAvailable=None,
            supplierId=None,
            supplierName=row["contact_person"] or row["supplier_contact"] or "未提供",
            supplierCity=None,
            supplierQualityRating=None,
            priceMin=_string_value(price["price_min"] if price else None),
            priceMax=_string_value(price["price_max"] if price else None),
            priceCurrency=_string_value(price["currency"] if price else None),
            priceSummary=price_summary,
            operationStatus=row["operation_status"],
            promotionStatus=row["promotion_status"],
            proposer=row["proposer"],
            logisticsTerm=row["logistics_term"],
            qualifications=row["qualifications"],
            hasDocuments=document_count > 0,
            documentCount=document_count,
            sourceId=_string_value(row["source_id"]),
            sourceFileName=row["source_file_name"],
            sourceSheet=row["source_sheet"],
            sourceRow=row["source_row"],
        )
        sort_price = min(usd_prices) if usd_prices else float("inf")
        products.append((sort_price, row["product_name"], product))

    products.sort(key=lambda item: (item[0], item[1]))
    result_products = [product for _, _, product in products[:limit]]
    response_message = None
    if missing_source_file_names:
        response_message = "Source files not found: " + ", ".join(missing_source_file_names)
    return ProductSearchResponse(products=result_products, message=response_message)
