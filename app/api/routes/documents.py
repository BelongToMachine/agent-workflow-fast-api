from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(prefix="/documents", tags=["documents"])

ArtifactKind = Literal["text", "code", "image", "sheet"]


class DocumentRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str | None
    created_at: str = Field(alias="createdAt")
    id: str
    kind: ArtifactKind
    title: str
    user_id: str = Field(alias="userId")
    workspace_id: str = Field(alias="workspaceId")


class DocumentWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    content: str
    is_manual_edit: bool = Field(default=False, alias="isManualEdit")
    kind: ArtifactKind
    title: str = Field(min_length=1, max_length=200)


DOCUMENT_COLUMNS = """
    SELECT
        "content" AS content,
        "createdAt" AS created_at,
        "id" AS id,
        "kind" AS kind,
        "title" AS title,
        "userId" AS user_id,
        "workspaceId" AS workspace_id
    FROM "Document"
"""
DOCUMENTS_BY_ID_QUERY = text(
    DOCUMENT_COLUMNS
    + """
    WHERE "id" = :document_id
      AND "userId" = :user_id
      AND "workspaceId" = :workspace_id
    ORDER BY "createdAt" ASC
    """
)
LATEST_DOCUMENT_QUERY = text(
    DOCUMENT_COLUMNS
    + """
    WHERE "id" = :document_id
      AND "workspaceId" = :workspace_id
    ORDER BY "createdAt" DESC
    LIMIT 1
    """
)
INSERT_DOCUMENT_QUERY = text(
    """
    INSERT INTO "Document"
        ("content", "createdAt", "id", "kind", "title", "userId", "workspaceId")
    VALUES
        (:content, CURRENT_TIMESTAMP, :document_id, :kind, :title, :user_id, :workspace_id)
    RETURNING
        "content" AS content,
        "createdAt" AS created_at,
        "id" AS id,
        "kind" AS kind,
        "title" AS title,
        "userId" AS user_id,
        "workspaceId" AS workspace_id
    """
)
UPDATE_DOCUMENT_QUERY = text(
    """
    UPDATE "Document"
    SET "content" = :content
    WHERE "id" = :document_id
      AND "createdAt" = :created_at
      AND "userId" = :user_id
      AND "workspaceId" = :workspace_id
    RETURNING
        "content" AS content,
        "createdAt" AS created_at,
        "id" AS id,
        "kind" AS kind,
        "title" AS title,
        "userId" AS user_id,
        "workspaceId" AS workspace_id
    """
)
DELETE_SUGGESTIONS_QUERY = text(
    """
    DELETE FROM "Suggestion"
    WHERE "documentId" = :document_id
      AND "documentCreatedAt" > :created_at
    """
)
DELETE_DOCUMENTS_QUERY = text(
    """
    DELETE FROM "Document"
    WHERE "id" = :document_id
      AND "userId" = :user_id
      AND "workspaceId" = :workspace_id
      AND "createdAt" > :created_at
    RETURNING
        "content" AS content,
        "createdAt" AS created_at,
        "id" AS id,
        "kind" AS kind,
        "title" AS title,
        "userId" AS user_id,
        "workspaceId" AS workspace_id
    """
)


def _iso_timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _document_record(row: dict[str, object]) -> DocumentRecord:
    return DocumentRecord(
        content=row["content"] if isinstance(row["content"], str) else None,
        createdAt=_iso_timestamp(row["created_at"]),
        id=str(row["id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        userId=str(row["user_id"]),
        workspaceId=str(row["workspace_id"]),
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


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timestamp.",
        ) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _require_persisted_identity(current_user: AuthenticatedUser) -> UUID:
    if current_user.is_development:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token or NextAuth bridge context is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error


@router.get("", response_model=list[DocumentRecord])
async def list_document_versions(
    id: str | None = Query(default=None),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[DocumentRecord] | JSONResponse:
    if not id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter id is missing.",
        )

    await require_workspace_permission(current_user, workspace_id, "document.read")
    user_id = _require_persisted_identity(current_user)
    document_id = _parse_document_id(id)

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                DOCUMENTS_BY_ID_QUERY,
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                },
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query document versions.")

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return [_document_record(dict(row)) for row in rows]


@router.post("", response_model=list[DocumentRecord])
async def write_document_version(
    payload: DocumentWriteRequest,
    id: str | None = Query(default=None),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[DocumentRecord] | JSONResponse:
    if not id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter id is required.",
        )

    await require_workspace_permission(current_user, workspace_id, "document.write")
    user_id = _require_persisted_identity(current_user)
    document_id = _parse_document_id(id)

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                latest_result = await connection.execute(
                    LATEST_DOCUMENT_QUERY,
                    {
                        "document_id": document_id,
                        "workspace_id": workspace_id,
                    },
                )
                latest = latest_result.mappings().first()
                if latest is not None and latest["user_id"] != user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="The document belongs to another user.",
                    )

                if payload.is_manual_edit:
                    if latest is None:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Document not found.",
                        )
                    result = await connection.execute(
                        UPDATE_DOCUMENT_QUERY,
                        {
                            "content": payload.content,
                            "created_at": latest["created_at"],
                            "document_id": document_id,
                            "user_id": user_id,
                            "workspace_id": workspace_id,
                        },
                    )
                else:
                    result = await connection.execute(
                        INSERT_DOCUMENT_QUERY,
                        {
                            "content": payload.content,
                            "document_id": document_id,
                            "kind": payload.kind,
                            "title": payload.title,
                            "user_id": user_id,
                            "workspace_id": workspace_id,
                        },
                    )
                row = result.mappings().first()
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not save the document.")

    if row is None:
        return _database_error("FastAPI could not load the saved document.")
    return [_document_record(dict(row))]


@router.delete("", response_model=list[DocumentRecord])
async def delete_document_versions(
    id: str | None = Query(default=None),
    timestamp: str | None = Query(default=None),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[DocumentRecord] | JSONResponse:
    if not id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter id is required.",
        )
    if not timestamp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter timestamp is required.",
        )

    await require_workspace_permission(current_user, workspace_id, "document.write")
    user_id = _require_persisted_identity(current_user)
    document_id = _parse_document_id(id)
    created_after = _parse_timestamp(timestamp)

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                latest_result = await connection.execute(
                    LATEST_DOCUMENT_QUERY,
                    {
                        "document_id": document_id,
                        "workspace_id": workspace_id,
                    },
                )
                latest = latest_result.mappings().first()
                if latest is None or latest["user_id"] != user_id:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Document not found.",
                    )

                await connection.execute(
                    DELETE_SUGGESTIONS_QUERY,
                    {"created_at": created_after, "document_id": document_id},
                )
                result = await connection.execute(
                    DELETE_DOCUMENTS_QUERY,
                    {
                        "created_at": created_after,
                        "document_id": document_id,
                        "user_id": user_id,
                        "workspace_id": workspace_id,
                    },
                )
                rows = result.mappings().all()
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not delete document versions.")

    return [_document_record(dict(row)) for row in rows]
