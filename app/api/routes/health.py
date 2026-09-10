from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.errors import DatabaseServiceError, DatabaseUnavailableError
from app.db.session import get_db_connection

router = APIRouter(tags=["health"])


@router.get("/healthz")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/readyz")
async def readiness_check() -> dict[str, str]:
    """Confirm that this API instance can acquire and use a database connection."""
    try:
        async with get_db_connection() as connection:
            await connection.execute(text("SELECT 1"))
    except DatabaseServiceError:
        raise
    except SQLAlchemyError as error:
        raise DatabaseUnavailableError() from error

    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }
