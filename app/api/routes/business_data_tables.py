import json
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.knowledge_access import get_authorized_source_ids
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(prefix="/admin/data-tables", tags=["business-data-tables"])

PRICE_COLUMNS: dict[str, str] = {
    "id": 'price."id"',
    "researchId": 'price."researchId"',
    "productName": 'research."productName"',
    "category": 'research."category"',
    "brand": 'research."brand"',
    "sourceFileId": 'price."sourceFileId"',
    "sourceFileName": 'source."originalName"',
    "variant": 'price."variant"',
    "priceMin": 'price."priceMin"',
    "priceMax": 'price."priceMax"',
    "currency": 'price."currency"',
    "priceType": 'price."priceType"',
    "sourceSheet": 'price."sourceSheet"',
    "sourceRow": 'price."sourceRow"',
}
PRICE_TEXT_FILTER_FIELDS = frozenset(
    {
        "id",
        "researchId",
        "productName",
        "category",
        "brand",
        "sourceFileId",
        "sourceFileName",
        "variant",
        "currency",
        "priceType",
        "sourceSheet",
    }
)
PRICE_NUMBER_FILTER_FIELDS = frozenset({"priceMin", "priceMax", "sourceRow"})
PRICE_SEARCH_FIELDS = (
    "id",
    "researchId",
    "productName",
    "category",
    "brand",
    "sourceFileId",
    "sourceFileName",
    "variant",
    "priceMin",
    "priceMax",
    "currency",
    "priceType",
    "sourceSheet",
    "sourceRow",
)
TEXT_FILTER_OPERATORS = frozenset(
    {
        "contains",
        "notContains",
        "equals",
        "notEqual",
        "startsWith",
        "endsWith",
        "blank",
        "notBlank",
    }
)
NUMBER_FILTER_OPERATORS = frozenset(
    {
        "equals",
        "notEqual",
        "lessThan",
        "lessThanOrEqual",
        "greaterThan",
        "greaterThanOrEqual",
        "inRange",
        "blank",
        "notBlank",
    }
)
NUMBER_SQL_OPERATORS = {
    "equals": "=",
    "notEqual": "<>",
    "lessThan": "<",
    "lessThanOrEqual": "<=",
    "greaterThan": ">",
    "greaterThanOrEqual": ">=",
}

PRICE_FROM_WHERE = """
    FROM "ProductPrice" AS price
    INNER JOIN "KnowledgeFile" AS source
        ON source."id" = price."sourceFileId"
    INNER JOIN "RealProductResearch" AS research
        ON research."id" = price."researchId"
       AND research."sourceFileId" = price."sourceFileId"
    INNER JOIN "KnowledgeFile" AS research_source
        ON research_source."id" = research."sourceFileId"
    WHERE {conditions}
"""


class ProductPriceRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    research_id: UUID = Field(alias="researchId")
    product_name: str = Field(alias="productName")
    category: str | None = None
    brand: str | None = None
    source_file_id: UUID = Field(alias="sourceFileId")
    source_file_name: str = Field(alias="sourceFileName")
    variant: str
    price_min: Decimal = Field(alias="priceMin")
    price_max: Decimal | None = Field(default=None, alias="priceMax")
    currency: str
    price_type: str = Field(alias="priceType")
    source_sheet: str = Field(alias="sourceSheet")
    source_row: int = Field(alias="sourceRow")


class ProductPriceRowsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rows: list[ProductPriceRow]
    offset: int
    limit: int
    total: int
    has_more: bool = Field(alias="hasMore")


def _invalid_query(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _load_json_object(value: str | None, label: str) -> dict[str, Any]:
    if value is None or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise _invalid_query(f"{label} must be valid JSON.") from error
    if not isinstance(parsed, dict):
        raise _invalid_query(f"{label} must be a JSON object.")
    return parsed


def _parse_sort_model(value: str | None) -> list[tuple[str, Literal["asc", "desc"]]]:
    if value is None or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise _invalid_query("sort must be valid JSON.") from error
    if not isinstance(parsed, list) or len(parsed) > 1:
        raise _invalid_query("ProductPrice supports sorting by one column at a time.")

    result: list[tuple[str, Literal["asc", "desc"]]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise _invalid_query("Each sort entry must be an object.")
        field = item.get("field")
        direction = item.get("direction")
        if (
            not isinstance(field, str)
            or field not in PRICE_COLUMNS
            or not isinstance(direction, str)
            or direction not in {"asc", "desc"}
        ):
            raise _invalid_query("The requested sort field or direction is not supported.")
        result.append((field, direction))
    return result


def _normalize_filter_condition(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_query(f"The filter for {field} must be an object.")

    expected_filter_type = "number" if field in PRICE_NUMBER_FILTER_FIELDS else "text"
    filter_type = value.get("filterType", expected_filter_type)
    if filter_type != expected_filter_type:
        raise _invalid_query(f"The filter type for {field} is not supported.")

    operator = value.get("type")
    allowed_operators = (
        NUMBER_FILTER_OPERATORS if expected_filter_type == "number" else TEXT_FILTER_OPERATORS
    )
    if not isinstance(operator, str) or operator not in allowed_operators:
        raise _invalid_query(f"The filter operator for {field} is not supported.")

    normalized: dict[str, Any] = {"operator": operator, "filterType": expected_filter_type}
    if operator in {"blank", "notBlank"}:
        return normalized

    raw_filter = value.get("filter")
    if raw_filter is None:
        raise _invalid_query(f"A filter value is required for {field}.")
    if expected_filter_type == "number":
        try:
            parsed_filter = Decimal(str(raw_filter))
        except (InvalidOperation, ValueError) as error:
            raise _invalid_query(f"The numeric filter for {field} is invalid.") from error
        if not parsed_filter.is_finite():
            raise _invalid_query(f"The numeric filter for {field} is invalid.")
        normalized["filter"] = parsed_filter
        if operator == "inRange":
            raw_filter_to = value.get("filterTo")
            if raw_filter_to is None:
                raise _invalid_query(f"A range end is required for {field}.")
            try:
                parsed_filter_to = Decimal(str(raw_filter_to))
            except (InvalidOperation, ValueError) as error:
                raise _invalid_query(f"The numeric filter range for {field} is invalid.") from error
            if not parsed_filter_to.is_finite():
                raise _invalid_query(f"The numeric filter range for {field} is invalid.")
            normalized["filterTo"] = parsed_filter_to
    else:
        parsed_filter = str(raw_filter)
        if len(parsed_filter) > 200:
            raise _invalid_query(f"The text filter for {field} is too long.")
        normalized["filter"] = parsed_filter
    return normalized


def _parse_filter_model(value: str | None) -> dict[str, dict[str, Any]]:
    parsed = _load_json_object(value, "filters")
    if len(parsed) > len(PRICE_COLUMNS):
        raise _invalid_query("Too many ProductPrice column filters were supplied.")

    normalized: dict[str, dict[str, Any]] = {}
    for field, model in parsed.items():
        if field not in PRICE_COLUMNS:
            raise _invalid_query(f"The filter field {field} is not supported.")
        if field not in PRICE_TEXT_FILTER_FIELDS | PRICE_NUMBER_FILTER_FIELDS:
            raise _invalid_query(f"The filter field {field} is not supported.")
        if not isinstance(model, dict):
            raise _invalid_query(f"The filter for {field} must be an object.")

        conditions = model.get("conditions")
        if conditions is None and ("condition1" in model or "condition2" in model):
            conditions = [
                item for item in (model.get("condition1"), model.get("condition2")) if item
            ]
        if conditions is not None:
            if not isinstance(conditions, list) or not 1 <= len(conditions) <= 2:
                raise _invalid_query(f"The filter conditions for {field} are invalid.")
            operator = model.get("operator", "AND")
            if not isinstance(operator, str) or operator not in {"AND", "OR"}:
                raise _invalid_query(f"The filter join operator for {field} is invalid.")
            normalized[field] = {
                "operator": operator,
                "conditions": [
                    _normalize_filter_condition(condition, field) for condition in conditions
                ],
            }
        else:
            normalized[field] = {
                "operator": "AND",
                "conditions": [_normalize_filter_condition(model, field)],
            }
    return normalized


def _filter_condition_sql(
    field: str,
    condition: dict[str, Any],
    params: dict[str, object],
    index: int,
) -> tuple[str, int]:
    expression = PRICE_COLUMNS[field]
    operator = condition["operator"]
    filter_type = condition["filterType"]
    if operator == "blank":
        if filter_type == "number":
            return f"{expression} IS NULL", index
        return f"COALESCE(CAST({expression} AS TEXT), '') = ''", index
    if operator == "notBlank":
        if filter_type == "number":
            return f"{expression} IS NOT NULL", index
        return f"COALESCE(CAST({expression} AS TEXT), '') <> ''", index

    bind_name = f"filter_{index}"
    params[bind_name] = condition["filter"]
    if filter_type == "number":
        if operator == "inRange":
            end_bind_name = f"filter_{index + 1}"
            params[end_bind_name] = condition["filterTo"]
            return f"{expression} BETWEEN :{bind_name} AND :{end_bind_name}", index + 2
        return f"{expression} {NUMBER_SQL_OPERATORS[operator]} :{bind_name}", index + 1

    text_expression = f"CAST({expression} AS TEXT)"
    text_value = str(condition["filter"])
    if operator == "contains":
        params[bind_name] = f"%{text_value}%"
        predicate = "ILIKE"
    elif operator == "notContains":
        params[bind_name] = f"%{text_value}%"
        predicate = "NOT ILIKE"
    elif operator == "startsWith":
        params[bind_name] = f"{text_value}%"
        predicate = "ILIKE"
    elif operator == "endsWith":
        params[bind_name] = f"%{text_value}"
        predicate = "ILIKE"
    elif operator == "notEqual":
        params[bind_name] = text_value
        predicate = "NOT ILIKE"
    else:
        params[bind_name] = text_value
        predicate = "ILIKE"
    return f"{text_expression} {predicate} :{bind_name}", index + 1


def _build_product_price_queries(
    *,
    workspace_id: UUID,
    query: str | None,
    sort: list[tuple[str, Literal["asc", "desc"]]],
    filters: dict[str, dict[str, Any]],
    offset: int,
    limit: int,
    authorized_source_ids: list[UUID] | None = None,
) -> tuple[object, object, dict[str, object]]:
    conditions = [
        'source."workspaceId" = :workspace_id',
        "source.\"status\" = 'ready'",
        'research_source."workspaceId" = :workspace_id',
    ]
    params: dict[str, object] = {
        "workspace_id": str(workspace_id),
        "offset": offset,
        "limit": limit,
    }
    if authorized_source_ids is not None:
        if not authorized_source_ids:
            conditions.append("FALSE")
        else:
            conditions.append('source."knowledgeBaseId" IN :authorized_source_ids')
            params["authorized_source_ids"] = authorized_source_ids

    normalized_query = query.strip() if query else ""
    if normalized_query:
        searchable_sql = " OR ".join(
            f"CAST({PRICE_COLUMNS[field]} AS TEXT) ILIKE :query_pattern"
            for field in PRICE_SEARCH_FIELDS
        )
        conditions.append(f"({searchable_sql})")
        params["query_pattern"] = f"%{normalized_query}%"

    filter_index = 0
    for field, model in filters.items():
        condition_sql = []
        for condition in model["conditions"]:
            expression, filter_index = _filter_condition_sql(
                field,
                condition,
                params,
                filter_index,
            )
            condition_sql.append(expression)
        joiner = " OR " if model["operator"] == "OR" else " AND "
        conditions.append("(" + joiner.join(condition_sql) + ")")

    where = " AND ".join(conditions)
    count_query = text("SELECT COUNT(*) AS total " + PRICE_FROM_WHERE.format(conditions=where))
    row_expressions = ",\n        ".join(
        f'{PRICE_COLUMNS[field]} AS "{field}"' for field in PRICE_COLUMNS
    )
    select_columns = ",\n        ".join(
        (
            row_expressions,
            'source."originalName" AS "sourceFileName"',
        )
    )
    order_by = [f"{PRICE_COLUMNS[field]} {direction.upper()}" for field, direction in sort]
    if not any(field == "id" for field, _ in sort):
        order_by.append(f"{PRICE_COLUMNS['id']} ASC")
    rows_query = text(
        f"SELECT {select_columns} "
        + PRICE_FROM_WHERE.format(conditions=where)
        + " ORDER BY "
        + ", ".join(order_by)
        + " LIMIT :limit OFFSET :offset"
    )
    if authorized_source_ids:
        count_query = count_query.bindparams(bindparam("authorized_source_ids", expanding=True))
        rows_query = rows_query.bindparams(bindparam("authorized_source_ids", expanding=True))
    return count_query, rows_query, params


@router.get("/ProductPrice/rows", response_model=ProductPriceRowsResponse)
async def list_product_price_rows(
    current_user: AuthenticatedUser = Depends(get_current_user),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    query: str | None = Query(default=None, alias="q", max_length=200),
    sort_json: str | None = Query(default=None, alias="sort", max_length=1000),
    filters_json: str | None = Query(default=None, alias="filters", max_length=10000),
) -> ProductPriceRowsResponse:
    await require_workspace_permission(current_user, workspace_id, "knowledge.manage")
    authorized_source_ids = await get_authorized_source_ids(
        current_user,
        workspace_id,
        workspace_role=current_user.role,
        is_guest=current_user.is_guest,
    )
    if authorized_source_ids == []:
        return ProductPriceRowsResponse(
            rows=[],
            offset=offset,
            limit=limit,
            total=0,
            hasMore=False,
        )

    sort = _parse_sort_model(sort_json)
    filters = _parse_filter_model(filters_json)
    count_query, rows_query, params = _build_product_price_queries(
        workspace_id=workspace_id,
        query=query,
        sort=sort,
        filters=filters,
        offset=offset,
        limit=limit,
        authorized_source_ids=authorized_source_ids,
    )
    try:
        async with get_db_connection() as connection:
            count_result = await connection.execute(count_query, params)
            total = int(count_result.mappings().one()["total"])
            rows_result = await connection.execute(rows_query, params)
            rows = [ProductPriceRow.model_validate(row) for row in rows_result.mappings().all()]
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not connect to the business data database.",
        ) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FastAPI could not query ProductPrice rows.",
        ) from error

    return ProductPriceRowsResponse(
        rows=rows,
        offset=offset,
        limit=limit,
        total=total,
        hasMore=offset + len(rows) < total,
    )
