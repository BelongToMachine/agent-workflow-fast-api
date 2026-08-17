from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.workspace_access import require_workspace_permission
from app.services.attachments import (
    SUPPORTED_ATTACHMENT_TYPES,
    attachment_content_matches_type,
    build_attachment_storage,
    build_attachment_storage_key,
    create_local_attachment_token,
    safe_attachment_filename,
    verify_local_attachment_token,
)
from app.services.storage import (
    LocalKnowledgeStorage,
    S3KnowledgeStorage,
    StorageConfigurationError,
    StorageError,
)

router = APIRouter(prefix="/files", tags=["files"])


class AttachmentUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content_type: str = Field(alias="contentType")
    pathname: str
    url: str


def _disabled_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "code": "chat_attachments:disabled",
            "message": "FastAPI chat attachment uploads are disabled.",
        },
    )


def _storage_error(error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"code": "storage:unavailable", "cause": str(error)},
    )


@router.post("/upload", response_model=AttachmentUploadResponse)
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: UUID = Query(..., alias="workspace_id"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AttachmentUploadResponse | JSONResponse:
    await require_workspace_permission(current_user, workspace_id, "document.write")
    if not settings.chat_attachments_enabled:
        return _disabled_response()

    content_type = file.content_type or ""
    if content_type not in SUPPORTED_ATTACHMENT_TYPES:
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={"error": "File type should be JPEG or PNG."},
        )

    content = await file.read(settings.attachment_max_file_bytes + 1)
    if len(content) > settings.attachment_max_file_bytes:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"error": "File size should be less than 5MB."},
        )
    if not attachment_content_matches_type(content_type, content):
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={
                "code": "attachments:invalid_content",
                "error": "The uploaded bytes do not match the declared image type.",
            },
        )

    original_name = safe_attachment_filename(file.filename or "attachment")
    storage_key = build_attachment_storage_key(
        workspace_id,
        current_user.user_id,
        original_name,
    )
    try:
        storage = build_attachment_storage(settings)
        await storage.put(storage_key, content)
        if isinstance(storage, LocalKnowledgeStorage):
            token = create_local_attachment_token(
                settings,
                content_type=content_type,
                filename=original_name,
                storage_key=storage_key,
            )
            base_url = (
                settings.attachment_public_base_url or str(request.base_url)
            ).rstrip("/")
            url = f"{base_url}/api/v1/files/attachments/{quote(token, safe='')}"
        elif isinstance(storage, S3KnowledgeStorage):
            url = await storage.presigned_url(
                storage_key,
                settings.attachment_url_ttl_seconds,
            )
        else:
            raise StorageConfigurationError("Unsupported attachment storage backend.")
    except StorageConfigurationError as error:
        return _storage_error(error)
    except StorageError as error:
        return _storage_error(error)

    return AttachmentUploadResponse(
        contentType=content_type,
        pathname=storage_key,
        url=url,
    )


@router.get("/attachments/{token}", response_model=None)
async def download_local_attachment(
    token: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    payload = verify_local_attachment_token(settings, token)
    if payload is None or settings.attachment_storage_provider != "local":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        storage = build_attachment_storage(settings)
        if not isinstance(storage, LocalKnowledgeStorage):
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        content = await storage.read(payload["storageKey"])
    except (StorageConfigurationError, StorageError):
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return Response(
        content=content,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="{payload["name"]}"',
        },
        media_type=payload["contentType"],
    )
