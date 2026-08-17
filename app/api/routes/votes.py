from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.workspace_access import require_workspace_permission
from app.db.session import get_db_connection

router = APIRouter(tags=["votes"])


class VoteRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chat_id: str = Field(alias="chatId")
    message_id: str = Field(alias="messageId")
    is_upvoted: bool = Field(alias="isUpvoted")


class VoteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    chat_id: UUID = Field(alias="chatId")
    message_id: UUID = Field(alias="messageId")
    vote_type: str = Field(alias="type", pattern="^(up|down)$")


CHAT_OWNER_QUERY = text(
    """
    SELECT "userId" AS user_id, "workspaceId" AS workspace_id
    FROM "Chat"
    WHERE "id" = :chat_id
    LIMIT 1
    """
)
MESSAGE_QUERY = text(
    """
    SELECT "id"
    FROM "Message_v2"
    WHERE "id" = :message_id
      AND "chatId" = :chat_id
    LIMIT 1
    """
)
VOTES_QUERY = text(
    """
    SELECT
        "chatId" AS chat_id,
        "messageId" AS message_id,
        "isUpvoted" AS is_upvoted
    FROM "Vote_v2"
    WHERE "chatId" = :chat_id
    ORDER BY "messageId"
    """
)
UPSERT_VOTE_QUERY = text(
    """
    INSERT INTO "Vote_v2" ("chatId", "messageId", "isUpvoted")
    VALUES (:chat_id, :message_id, :is_upvoted)
    ON CONFLICT ("chatId", "messageId")
    DO UPDATE SET "isUpvoted" = EXCLUDED."isUpvoted"
    """
)


def _database_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "database:unavailable", "cause": message},
    )


async def _require_chat_owner(
    connection: object,
    *,
    chat_id: UUID,
    user_id: UUID,
    workspace_id: UUID,
    not_found_detail: str,
) -> None:
    result = await connection.execute(CHAT_OWNER_QUERY, {"chat_id": chat_id})
    chat = result.mappings().first()
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    if chat["user_id"] != user_id or chat["workspace_id"] != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The chat does not belong to this user or workspace.",
        )


def _local_user_id(current_user: AuthenticatedUser) -> UUID:
    try:
        return UUID(current_user.user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated user is not linked to a local workspace.",
        ) from error


@router.get("/votes", response_model=list[VoteRecord])
async def get_votes(
    chat_id: UUID = Query(..., alias="chatId"),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> list[VoteRecord] | JSONResponse:
    access = await require_workspace_permission(current_user, workspace_id, "chat.read")
    if access.is_development:
        return []

    user_id = _local_user_id(current_user)
    try:
        async with get_db_connection() as connection:
            await _require_chat_owner(
                connection,
                chat_id=chat_id,
                not_found_detail="Chat not found.",
                user_id=user_id,
                workspace_id=workspace_id,
            )
            result = await connection.execute(VOTES_QUERY, {"chat_id": chat_id})
            rows = result.mappings().all()
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not query chat votes.")

    return [
        VoteRecord(
            chatId=str(row["chat_id"]),
            isUpvoted=bool(row["is_upvoted"]),
            messageId=str(row["message_id"]),
        )
        for row in rows
    ]


@router.patch("/votes", response_model=None)
async def save_vote(
    payload: VoteRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> PlainTextResponse | JSONResponse:
    access = await require_workspace_permission(current_user, workspace_id, "chat.write")
    if access.is_development:
        return PlainTextResponse("Message voted", status_code=status.HTTP_200_OK)

    user_id = _local_user_id(current_user)
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                await _require_chat_owner(
                    connection,
                    chat_id=payload.chat_id,
                    not_found_detail="Vote chat not found.",
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                message_result = await connection.execute(
                    MESSAGE_QUERY,
                    {
                        "chat_id": payload.chat_id,
                        "message_id": payload.message_id,
                    },
                )
                if message_result.mappings().first() is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Vote message not found.",
                    )
                await connection.execute(
                    UPSERT_VOTE_QUERY,
                    {
                        "chat_id": payload.chat_id,
                        "is_upvoted": payload.vote_type == "up",
                        "message_id": payload.message_id,
                    },
                )
    except HTTPException:
        raise
    except RuntimeError as error:
        return _database_error(str(error))
    except SQLAlchemyError:
        return _database_error("FastAPI could not save the chat vote.")

    return PlainTextResponse("Message voted", status_code=status.HTTP_200_OK)
