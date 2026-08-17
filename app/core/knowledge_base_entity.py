from app.core.config import Settings, get_settings

LEGACY_KNOWLEDGE_BASE_TABLE = '"KnowledgeSource"'
KNOWLEDGE_BASE_TABLE = '"KnowledgeBase"'


def knowledge_base_table(settings: Settings | None = None) -> str:
    """Return the SQL relation used as the FastAPI knowledge-base boundary."""
    active_settings = settings or get_settings()
    return (
        KNOWLEDGE_BASE_TABLE
        if active_settings.knowledge_base_entity_enabled
        else LEGACY_KNOWLEDGE_BASE_TABLE
    )


def knowledge_base_table_name(settings: Settings | None = None) -> str:
    return (
        "KnowledgeBase"
        if knowledge_base_table(settings) == KNOWLEDGE_BASE_TABLE
        else "KnowledgeSource"
    )


def render_knowledge_base_query(template: str, settings: Settings | None = None) -> str:
    return template.replace("{knowledge_base_table}", knowledge_base_table(settings))
