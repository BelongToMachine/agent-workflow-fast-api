from fastapi import APIRouter

from app.api.routes.admin_knowledge_grants import router as admin_knowledge_grants_router
from app.api.routes.admin_members import router as admin_members_router
from app.api.routes.agents import router as agents_router
from app.api.routes.attachments import router as attachments_router
from app.api.routes.auth_bootstrap import router as auth_bootstrap_router
from app.api.routes.chat import router as chat_router
from app.api.routes.chats import router as chats_router
from app.api.routes.content import router as content_router
from app.api.routes.dev_oidc import router as dev_oidc_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge_bases import router as knowledge_bases_router
from app.api.routes.knowledge_files import router as knowledge_files_router
from app.api.routes.knowledge_search import router as knowledge_search_router
from app.api.routes.knowledge_sources import router as knowledge_sources_router
from app.api.routes.me import router as me_router
from app.api.routes.models import router as models_router
from app.api.routes.products import router as products_router
from app.api.routes.suggestions import router as suggestions_router
from app.api.routes.votes import router as votes_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(agents_router)
api_router.include_router(attachments_router)
api_router.include_router(auth_bootstrap_router)
api_router.include_router(admin_knowledge_grants_router)
api_router.include_router(admin_members_router)
api_router.include_router(chat_router)
api_router.include_router(chats_router)
api_router.include_router(content_router)
api_router.include_router(dev_oidc_router)
api_router.include_router(documents_router)
api_router.include_router(knowledge_sources_router)
api_router.include_router(knowledge_files_router)
api_router.include_router(knowledge_bases_router)
api_router.include_router(knowledge_search_router)
api_router.include_router(me_router)
api_router.include_router(models_router)
api_router.include_router(products_router)
api_router.include_router(suggestions_router)
api_router.include_router(votes_router)
