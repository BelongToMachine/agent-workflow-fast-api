from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(tags=["chats"])


class ChatSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    created_at: str = Field(alias="createdAt")
    title: str
    user_id: str = Field(alias="userId")
    visibility: str
    workspace_id: str = Field(alias="workspaceId")


class ChatHistoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chats: list[ChatSummary]
    has_more: bool = Field(alias="hasMore")


CHAT_COLUMNS = """
    SELECT
        chat."id" AS id,
        chat."createdAt" AS created_at,
        chat."title" AS title,
        chat."userId" AS user_id,
        chat."visibility" AS visibility,
        chat."workspaceId" AS workspace_id
    FROM "Chat" AS chat
"""
CHAT_BY_ID_QUERY = text(
    """
    SELECT "id", "title", "userId" AS user_id, "visibility", "workspaceId" AS workspace_id
    FROM "Chat"
    WHERE "id" = :chat_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)
CHAT_BASE_CONDITIONS = (
    'chat."userId" = :user_id',
    'chat."workspaceId" = :workspace_id',
)

CHAT_ANCHOR_QUERY = text(
    """
    SELECT "id", "createdAt" AS created_at
    FROM "Chat"
    WHERE "id" = :chat_id
      AND "userId" = :user_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

DELETE_CHAT_CHILDREN_QUERIES = (
    text('DELETE FROM "Vote_v2" WHERE "chatId" IN :chat_ids').bindparams(
        bindparam("chat_ids", expanding=True)
    ),
    text('DELETE FROM "Message_v2" WHERE "chatId" IN :chat_ids').bindparams(
        bindparam("chat_ids", expanding=True)
    ),
    text('DELETE FROM "Stream" WHERE "chatId" IN :chat_ids').bindparams(
        bindparam("chat_ids", expanding=True)
    ),
)


def _iso_timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _chat_summary(row: dict[str, object]) -> ChatSummary:
    return ChatSummary(
        id=str(row["id"]),
        createdAt=_iso_timestamp(row["created_at"]),
        title=str(row["title"]),
        userId=str(row["user_id"]),
        visibility=str(row["visibility"]),
        workspaceId=str(row["workspace_id"]),
    )


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


async def _find_cursor(
    connection: object,
    *,
    cursor_id: UUID,
    user_id: UUID,
    workspace_id: UUID,
) -> dict[str, object]:
    result = await connection.execute(
        CHAT_ANCHOR_QUERY,
        {
            "chat_id": cursor_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
        },
    )
    cursor = result.mappings().first()
    if cursor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat cursor not found in this workspace.",
        )
    return dict(cursor)


@router.get("/chats", response_model=ChatHistoryResponse)
async def list_chats(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    limit: int = Query(default=10, ge=1, le=50),
    starting_after: UUID | None = Query(default=None, alias="starting_after"),
    ending_before: UUID | None = Query(default=None, alias="ending_before"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ChatHistoryResponse | JSONResponse:
    if starting_after and ending_before:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "code": "bad_request:api",
                "message": "Only one of starting_after or ending_before can be provided.",
            },
        )

    access = await require_workspace_permission(current_user, workspace_id, "chat.read")
    if access.is_development:
        # The local development identity has no persisted user row or chat history.
        return ChatHistoryResponse(chats=[], hasMore=False)

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    try:
        async with get_db_connection() as connection:
            conditions = list(CHAT_BASE_CONDITIONS)
            params: dict[str, object] = {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "limit": limit + 1,
            }

            if starting_after or ending_before:
                cursor_id = starting_after or ending_before
                cursor = await _find_cursor(
                    connection,
                    cursor_id=cursor_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                params["cursor_created_at"] = cursor["created_at"]
                params["cursor_id"] = cursor["id"]
                if starting_after:
                    conditions.append(
                        '(chat."createdAt" > :cursor_created_at OR '
                        '(chat."createdAt" = :cursor_created_at '
                        'AND chat."id" > :cursor_id))'
                    )
                else:
                    conditions.append(
                        '(chat."createdAt" < :cursor_created_at OR '
                        '(chat."createdAt" = :cursor_created_at '
                        'AND chat."id" < :cursor_id))'
                    )

            query = text(
                CHAT_COLUMNS
                + " WHERE "
                + " AND ".join(conditions)
                + ' ORDER BY chat."createdAt" DESC, chat."id" DESC LIMIT :limit'
            )
            result = await connection.execute(query, params)
            rows = result.mappings().all()
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query chat history.")

    has_more = len(rows) > limit
    return ChatHistoryResponse(
        chats=[_chat_summary(dict(row)) for row in rows[:limit]],
        hasMore=has_more,
    )


@router.delete("/chats", response_model=None)
async def delete_chats(
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, int] | JSONResponse:
    access = await require_workspace_permission(current_user, workspace_id, "chat.delete")
    if access.is_development:
        return {"deletedCount": 0}

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                chat_result = await connection.execute(
                    text(
                        'SELECT "id" FROM "Chat" '
                        'WHERE "userId" = :user_id AND "workspaceId" = :workspace_id'
                    ),
                    {"user_id": user_id, "workspace_id": workspace_id},
                )
                chat_ids = [row["id"] for row in chat_result.mappings().all()]
                if not chat_ids:
                    return {"deletedCount": 0}

                for query in DELETE_CHAT_CHILDREN_QUERIES:
                    await connection.execute(query, {"chat_ids": chat_ids})

                deleted_result = await connection.execute(
                    text(
                        'DELETE FROM "Chat" '
                        'WHERE "userId" = :user_id AND "workspaceId" = :workspace_id '
                        'RETURNING "id"'
                    ),
                    {"user_id": user_id, "workspace_id": workspace_id},
                )
                deleted_count = len(deleted_result.mappings().all())
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not delete chat history.")

    return {"deletedCount": deleted_count}


@router.delete("/chats/{chat_id}", response_model=None)
async def delete_chat(
    chat_id: UUID,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str] | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "chat.delete")
    if current_user.is_development:
        return {"id": str(chat_id)}

    try:
        user_id = UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error

    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                chat_result = await connection.execute(
                    CHAT_BY_ID_QUERY,
                    {"chat_id": chat_id, "workspace_id": workspace_id},
                )
                chat_row = chat_result.mappings().first()
                if chat_row is None or chat_row["user_id"] != user_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="The chat does not belong to this user.",
                    )

                for query in DELETE_CHAT_CHILDREN_QUERIES:
                    await connection.execute(query, {"chat_ids": [chat_id]})
                await connection.execute(
                    text('DELETE FROM "Chat" WHERE "id" = :chat_id'),
                    {"chat_id": chat_id},
                )
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not delete the chat.")

    return {"id": str(chat_id)}
