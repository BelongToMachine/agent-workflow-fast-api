from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.admin import install_sqladmin
from app.api.errors import database_service_error_handler, structured_http_exception_handler
from app.api.router import api_router
from app.core.config import get_settings, validate_runtime_settings
from app.core.csrf import CSRFMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from app.db.errors import DatabaseServiceError
from app.db.session import get_engine
from app.services.agent_trace import configure_agent_trace_file_logging


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime_settings(settings)

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        configure_agent_trace_file_logging(settings)
        yield

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend service for the Asianode Agent platform.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_headers=["*"],
        allow_methods=["*"],
        expose_headers=[REQUEST_ID_HEADER],
        allow_origins=[
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if origin.strip()
        ],
    )
    application.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    application.add_middleware(
        CSRFMiddleware,
        allowed_origins=[
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if origin.strip()
        ],
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_exception_handler(DatabaseServiceError, database_service_error_handler)
    application.add_exception_handler(HTTPException, structured_http_exception_handler)
    application.include_router(api_router)
    if settings.sqladmin_enabled:
        install_sqladmin(application, settings, get_engine())

    @application.get("/", tags=["meta"])
    def read_root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "status": "running",
            "docs": "/docs",
        }

    return application


app = create_app()
