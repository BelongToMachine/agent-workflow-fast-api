from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.content import router as content_router
from app.api.routes.health import router as health_router
from app.api.routes.products import router as products_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(chat_router)
api_router.include_router(content_router)
api_router.include_router(products_router)
