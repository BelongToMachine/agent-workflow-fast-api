import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.me import CurrentUserResponse, build_current_user_response
from app.core.auth import ExternalPrincipal, get_external_principal
from app.core.identity import (
    BootstrapResultError,
    UserSuspended,
    bootstrap_external_identity,
)
from app.db.session import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["identity"])


@router.post("/bootstrap", response_model=CurrentUserResponse)
async def bootstrap_auth_identity(
    principal: ExternalPrincipal = Depends(get_external_principal),
) -> CurrentUserResponse:
    """Initialize a local user for a valid Logto identity.

    Bootstrap is intentionally idempotent and never grants workspace access.
    Memberships must be created by a separate owner/admin workflow.
    """
    try:
        async with get_db_connection() as connection:
            async with connection.begin():
                current_user = await bootstrap_external_identity(connection, principal)
                response = await build_current_user_response(connection, current_user)
    except UserSuspended as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user:suspended",
        ) from error
    except (BootstrapResultError, RuntimeError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication identity storage is unavailable.",
        ) from error

    subject_hash = hashlib.sha256(principal.subject.encode("utf-8")).hexdigest()[:16]
    logger.info(
        "External authentication identity bootstrapped",
        extra={
            "auth_provider": "logto",
            "external_subject_hash": subject_hash,
            "local_user_id": response.user_id,
            "access_state": response.access_state,
        },
    )
    return response
