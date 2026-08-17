from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db_connection

router = APIRouter(tags=["products"])


class ProductSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: str = Field(alias="productId")
    name_en: str = Field(alias="nameEn")
    category: str | None = None
    material: str | None = None
    supplier_name: str | None = Field(default=None, alias="supplierName")
    shipping_time: str | None = Field(default=None, alias="shippingTime")
    source_id: UUID | None = Field(default=None, alias="sourceId")
    source_file_name: str | None = Field(default=None, alias="sourceFileName")
    source_sheet: str | None = Field(default=None, alias="sourceSheet")
    source_row: int | None = Field(default=None, alias="sourceRow")


class ProductSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    products: list[ProductSummary]
    source: str = "enterprise"


PRODUCT_SEARCH_QUERY = text(
    '''
    SELECT
        research."id" AS product_id,
        research."productName" AS name_en,
        research."category" AS category,
        research."productFeatures" AS material,
        COALESCE(research."contactPerson", research."supplierContact") AS supplier_name,
        research."shippingTime" AS shipping_time,
        research."sourceId" AS source_id,
        source."displayName" AS source_file_name,
        research."sourceSheet" AS source_sheet,
        research."sourceRow" AS source_row
    FROM "RealProductResearch" AS research
    INNER JOIN "KnowledgeSource" AS source
        ON source."id" = research."sourceId"
    WHERE source."workspaceId" = :workspace_id
      AND source."status" = 'ready'
      AND (
          CAST(:query AS TEXT) IS NULL
          OR research."productName" ILIKE :query_pattern
          OR research."category" ILIKE :query_pattern
          OR research."productHighlights" ILIKE :query_pattern
          OR research."productFeatures" ILIKE :query_pattern
      )
      AND (
          CAST(:category AS TEXT) IS NULL
          OR research."category" ILIKE :category_pattern
      )
    ORDER BY research."productName" ASC
    LIMIT :limit
    '''
)


def _pattern(value: str | None) -> str | None:
    return f"%{value.strip()}%" if value and value.strip() else None


@router.get("/products", response_model=ProductSearchResponse)
async def search_products(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    query: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=10, ge=1, le=50),
) -> ProductSearchResponse | JSONResponse:
    params = {
        "category": _pattern(category),
        "category_pattern": _pattern(category),
        "limit": limit,
        "query": _pattern(query),
        "query_pattern": _pattern(query),
        "workspace_id": str(workspace_id),
    }

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(PRODUCT_SEARCH_QUERY, params)
            rows = result.mappings().all()
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

    products = [
        ProductSummary.model_validate(
            {
                **row,
                "product_id": str(row["product_id"]),
            }
        )
        for row in rows
    ]

    return ProductSearchResponse(
        products=products
    )
