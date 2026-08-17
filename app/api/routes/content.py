from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db_connection

router = APIRouter(tags=["content"])


class ContentSearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace_id: UUID = Field(alias="workspaceId")
    account: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=10, ge=1, le=20)
    product: str | None = Field(default=None, max_length=200)
    query: str | None = Field(default=None, max_length=500)
    record_type: Literal["account", "copy", "edit_plan", "shoot_plan", "topic"] | None = Field(
        default=None, alias="recordType"
    )
    source_file_names: list[str] | None = Field(
        default=None, alias="sourceFileNames", max_length=50
    )
    status: str | None = Field(default=None, max_length=100)
    submitter: str | None = Field(default=None, max_length=200)


class ContentRecordSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_direction: str | None = Field(default=None, alias="accountDirection")
    account_name: str | None = Field(default=None, alias="accountName")
    account_type: str | None = Field(default=None, alias="accountType")
    ai_materials: str | None = Field(default=None, alias="aiMaterials")
    attachment: str | None = None
    copy_text: str | None = Field(default=None, alias="copyText")
    copy_writer: str | None = Field(default=None, alias="copyWriter")
    language: str | None = None
    notes: str | None = None
    photographer: str | None = None
    platform: str | None = None
    planned_at: str | None = Field(default=None, alias="plannedAt")
    product: str | None = None
    record_type: str = Field(alias="recordType")
    reference_video: str | None = Field(default=None, alias="referenceVideo")
    revised_copy: str | None = Field(default=None, alias="revisedCopy")
    review_status: str | None = Field(default=None, alias="reviewStatus")
    script_document: str | None = Field(default=None, alias="scriptDocument")
    search_text: str = Field(alias="searchText")
    shoot_confirmed: str | None = Field(default=None, alias="shootConfirmed")
    shooting_scene: str | None = Field(default=None, alias="shootingScene")
    source_row: int = Field(alias="sourceRow")
    source_sheet: str = Field(alias="sourceSheet")
    source_id: str = Field(alias="sourceId")
    source_file_name: str | None = Field(default=None, alias="sourceFileName")
    submitter: str | None = None
    tags: str | None = None
    target_topic: str | None = Field(default=None, alias="targetTopic")
    title: str | None = None
    usage_status: str | None = Field(default=None, alias="usageStatus")
    video_type: str | None = Field(default=None, alias="videoType")


class ContentSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    records: list[ContentRecordSummary]
    source: str = "enterprise"
    source_table: str = Field(default="ContentRecord", alias="sourceTable")
    message: str | None = None


CONTENT_SEARCH_SELECT = """
    SELECT
        record."accountDirection" AS account_direction,
        record."accountName" AS account_name,
        record."accountType" AS account_type,
        record."aiMaterials" AS ai_materials,
        record."attachment" AS attachment,
        record."copyText" AS copy_text,
        record."copyWriter" AS copy_writer,
        record."language" AS language,
        record."notes" AS notes,
        record."photographer" AS photographer,
        record."platform" AS platform,
        record."plannedAt" AS planned_at,
        record."product" AS product,
        record."recordType" AS record_type,
        record."referenceVideo" AS reference_video,
        record."revisedCopy" AS revised_copy,
        record."reviewStatus" AS review_status,
        record."scriptDocument" AS script_document,
        record."searchText" AS search_text,
        record."shootConfirmed" AS shoot_confirmed,
        record."shootingScene" AS shooting_scene,
        record."sourceRow" AS source_row,
        record."sourceSheet" AS source_sheet,
        record."sourceId" AS source_id,
        source."displayName" AS source_file_name,
        record."submitter" AS submitter,
        record."tags" AS tags,
        record."targetTopic" AS target_topic,
        record."title" AS title,
        record."usageStatus" AS usage_status,
        record."videoType" AS video_type
    FROM "ContentRecord" AS record
    INNER JOIN "KnowledgeSource" AS source
        ON source."id" = record."sourceId"
    WHERE {conditions}
    ORDER BY record."plannedAt" ASC, record."sourceRow" ASC
    LIMIT :limit
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


def _pattern(value: str | None) -> str | None:
    return f"%{value.strip()}%" if value and value.strip() else None


def _normalized_values(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values or [] if value.strip()))


def _build_content_search_query(
    *,
    workspace_id: UUID,
    account: str | None,
    language: str | None,
    product: str | None,
    query: str | None,
    record_type: str | None,
    status: str | None,
    submitter: str | None,
    source_ids: list[UUID],
    limit: int,
) -> tuple[object, dict[str, object]]:
    conditions = ['source."workspaceId" = :workspace_id']
    params: dict[str, object] = {
        "limit": limit,
        "workspace_id": str(workspace_id),
    }

    if source_ids:
        conditions.append('record."sourceId" IN :source_ids')
        params["source_ids"] = source_ids

    text_filters = {
        "language": ('record."language"', language),
        "product": ('record."product"', product),
        "record_type": ('record."recordType"', record_type),
    }
    for parameter_name, (column, value) in text_filters.items():
        if parameter_name == "record_type":
            if value and value.strip():
                conditions.append(f"{column} = :{parameter_name}")
                params[parameter_name] = value.strip()
            continue
        pattern = _pattern(value)
        if pattern:
            bind_name = f"{parameter_name}_pattern"
            conditions.append(f"{column} ILIKE :{bind_name}")
            params[bind_name] = pattern

    account_pattern = _pattern(account)
    if account_pattern:
        conditions.append(
            "("
            'record."accountName" ILIKE :account_pattern '
            'OR record."accountType" ILIKE :account_pattern '
            'OR record."accountDirection" ILIKE :account_pattern'
            ")"
        )
        params["account_pattern"] = account_pattern

    status_pattern = _pattern(status)
    if status_pattern:
        conditions.append(
            "("
            'record."reviewStatus" ILIKE :status_pattern '
            'OR record."usageStatus" ILIKE :status_pattern '
            'OR record."shootConfirmed" ILIKE :status_pattern'
            ")"
        )
        params["status_pattern"] = status_pattern

    submitter_pattern = _pattern(submitter)
    if submitter_pattern:
        conditions.append(
            "("
            'record."submitter" ILIKE :submitter_pattern '
            'OR record."copyWriter" ILIKE :submitter_pattern '
            'OR record."photographer" ILIKE :submitter_pattern'
            ")"
        )
        params["submitter_pattern"] = submitter_pattern

    query_pattern = _pattern(query)
    if query_pattern:
        conditions.append('record."searchText" ILIKE :query_pattern')
        params["query_pattern"] = query_pattern

    query_text = text(CONTENT_SEARCH_SELECT.format(conditions=" AND ".join(conditions)))
    bind_params = []
    if source_ids:
        bind_params.append(bindparam("source_ids", expanding=True))
    if bind_params:
        query_text = query_text.bindparams(*bind_params)
    return query_text, params


def _empty_response(message: str | None = None) -> ContentSearchResponse:
    return ContentSearchResponse(records=[], message=message)


def _source_file_message(missing_source_file_names: list[str]) -> str | None:
    if not missing_source_file_names:
        return None
    return "Source files not found: " + ", ".join(missing_source_file_names)


def _iso_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return str(value)

    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.post("/content/search", response_model=ContentSearchResponse)
async def search_content(
    payload: ContentSearchRequest,
    _current_user: AuthenticatedUser = Depends(get_current_user),
) -> ContentSearchResponse | JSONResponse:
    normalized_source_file_names = _normalized_values(payload.source_file_names)

    try:
        async with get_db_connection() as connection:
            source_ids: list[UUID] = []
            missing_source_file_names: list[str] = []
            if normalized_source_file_names:
                source_result = await connection.execute(
                    SOURCE_NAMES_QUERY,
                    {
                        "source_file_names": normalized_source_file_names,
                        "workspace_id": str(payload.workspace_id),
                    },
                )
                source_rows = source_result.mappings().all()
                found_source_names = {row["display_name"] for row in source_rows}
                source_ids = [row["source_id"] for row in source_rows]
                missing_source_file_names = [
                    name for name in normalized_source_file_names if name not in found_source_names
                ]
                if not source_ids:
                    return _empty_response(
                        "No knowledge source matched: " + ", ".join(normalized_source_file_names)
                    )

            search_query, params = _build_content_search_query(
                workspace_id=payload.workspace_id,
                account=payload.account,
                language=payload.language,
                product=payload.product,
                query=payload.query,
                record_type=payload.record_type,
                status=payload.status,
                submitter=payload.submitter,
                source_ids=source_ids,
                limit=payload.limit,
            )
            result = await connection.execute(search_query, params)
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

    records = [
        ContentRecordSummary(
            **{
                **row,
                "planned_at": _iso_timestamp(row["planned_at"]),
                "source_id": str(row["source_id"]),
            }
        )
        for row in rows
    ]
    return ContentSearchResponse(
        records=records,
        message=_source_file_message(missing_source_file_names),
    )
