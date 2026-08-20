from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import install_sqladmin
from app.api.router import api_router
from app.core.config import get_settings, validate_runtime_settings
from app.core.rate_limit import RateLimitMiddleware
from app.db.session import get_engine


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime_settings(settings)

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend service for the Asianode Agent platform.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_headers=["*"],
        allow_methods=["*"],
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
