KNOWLEDGE_BASE_TABLE = '"KnowledgeBase"'


def render_knowledge_base_query(template: str) -> str:
    """Render a query against the canonical KnowledgeBase entity."""
    return template.replace("{knowledge_base_table}", KNOWLEDGE_BASE_TABLE)
