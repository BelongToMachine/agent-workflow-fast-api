from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.knowledge_access import require_knowledge_base_permission
from app.db.session import get_db_connection
from app.services.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    embed_texts,
    vector_literal,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=20)


class KnowledgeSearchResult(BaseModel):
    chunk_id: str = Field(alias="chunkId")
    content: str
    file_id: str = Field(alias="fileId")
    file_name: str = Field(alias="fileName")
    score: float


class KnowledgeSearchResponse(BaseModel):
    results: list[KnowledgeSearchResult]


SEARCH_QUERY = text(
    """
    SELECT
        chunk."id" AS chunk_id,
        chunk."content" AS content,
        chunk."fileId" AS file_id,
        file."originalName" AS file_name,
        1 - (chunk."embedding" <=> CAST(:embedding AS vector)) AS score
    FROM "KnowledgeChunk" AS chunk
    INNER JOIN "KnowledgeFile" AS file ON file."id" = chunk."fileId"
    WHERE chunk."workspaceId" = :workspace_id
      AND chunk."knowledgeBaseId" = :knowledge_base_id
      AND chunk."embedding" IS NOT NULL
      AND file."status" = 'ready'
    ORDER BY chunk."embedding" <=> CAST(:embedding AS vector) ASC
    LIMIT :limit
    """
)


def _feature_disabled() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "code": "knowledge_search:disabled",
            "message": (
                "Knowledge vector search is disabled until its migration and provider "
                "are configured."
            ),
        },
    )


@router.post("/{knowledge_base_id}/search", response_model=KnowledgeSearchResponse)
async def search_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeSearchRequest,
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> KnowledgeSearchResponse | JSONResponse:
    await require_knowledge_base_permission(
        current_user,
        workspace_id,
        knowledge_base_id,
        "read",
    )
    if not settings.knowledge_embeddings_enabled:
        return _feature_disabled()

    try:
        vectors = await embed_texts([payload.query], settings)
    except EmbeddingConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except EmbeddingProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    try:
        async with get_db_connection() as connection:
            result = await connection.execute(
                SEARCH_QUERY,
                {
                    "embedding": vector_literal(vectors[0]),
                    "knowledge_base_id": knowledge_base_id,
                    "limit": payload.limit,
                    "workspace_id": workspace_id,
                },
            )
            rows = result.mappings().all()
    except RuntimeError as error:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "database:unavailable", "cause": str(error)},
        )
    except SQLAlchemyError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "database:unavailable",
                "cause": "FastAPI could not search knowledge chunks.",
            },
        )

    return KnowledgeSearchResponse(
        results=[
            KnowledgeSearchResult(
                chunkId=str(row["chunk_id"]),
                content=str(row["content"]),
                fileId=str(row["file_id"]),
                fileName=str(row["file_name"]),
                score=float(row["score"]),
            )
            for row in rows
        ]
    )
