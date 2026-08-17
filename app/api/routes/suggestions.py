from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(tags=["suggestions"])


class SuggestionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_at: str = Field(alias="createdAt")
    description: str | None
    document_created_at: str = Field(alias="documentCreatedAt")
    document_id: str = Field(alias="documentId")
    id: str
    is_resolved: bool = Field(alias="isResolved")
    original_text: str = Field(alias="originalText")
    suggested_text: str = Field(alias="suggestedText")
    user_id: str = Field(alias="userId")


DOCUMENT_ACCESS_QUERY = text(
    """
    SELECT "userId" AS user_id, "workspaceId" AS workspace_id
    FROM "Document"
    WHERE "id" = :document_id
    ORDER BY "createdAt" ASC
    LIMIT 1
    """
)
SUGGESTIONS_QUERY = text(
    """
    SELECT
        "createdAt" AS created_at,
        "description" AS description,
        "documentCreatedAt" AS document_created_at,
        "documentId" AS document_id,
        "id" AS id,
        "isResolved" AS is_resolved,
        "originalText" AS original_text,
        "suggestedText" AS suggested_text,
        "userId" AS user_id
    FROM "Suggestion"
    WHERE "documentId" = :document_id
    ORDER BY "createdAt" ASC, "id" ASC
    """
)


def _iso_timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _suggestion_record(row: dict[str, object]) -> SuggestionRecord:
    return SuggestionRecord(
        createdAt=_iso_timestamp(row["created_at"]),
        description=row["description"] if isinstance(row["description"], str) else None,
        documentCreatedAt=_iso_timestamp(row["document_created_at"]),
        documentId=str(row["document_id"]),
        id=str(row["id"]),
        isResolved=bool(row["is_resolved"]),
        originalText=str(row["original_text"]),
        suggestedText=str(row["suggested_text"]),
        userId=str(row["user_id"]),
    )


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


def _parse_document_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document id.",
        ) from error


def _local_user_id(current_user: AuthenticatedUser) -> UUID:
    try:
        return UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error


@router.get("/suggestions", response_model=list[SuggestionRecord])
async def list_suggestions(
    document_id: str = Query(..., alias="documentId"),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[SuggestionRecord] | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "document.read")
    user_id = _local_user_id(current_user)
    document_uuid = _parse_document_id(document_id)

    try:
        async with get_db_connection() as connection:
            document_result = await connection.execute(
                DOCUMENT_ACCESS_QUERY,
                {"document_id": document_uuid},
            )
            document = document_result.mappings().first()
            if (
                document is None
                or document["user_id"] != user_id
                or document["workspace_id"] != workspace_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The document is not accessible to this user.",
                )

            result = await connection.execute(
                SUGGESTIONS_QUERY,
                {"document_id": document_uuid},
            )
            rows = result.mappings().all()
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query document suggestions.")

    return [_suggestion_record(dict(row)) for row in rows]
