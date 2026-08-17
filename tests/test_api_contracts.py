from app.main import app

EXPECTED_API_PATHS = {
    "/api/v1/healthz",
    "/api/v1/me",
    "/api/v1/products",
    "/api/v1/content/search",
    "/api/v1/knowledge-sources",
    "/api/v1/knowledge-bases",
    "/api/v1/knowledge-bases/{knowledge_base_id}",
    "/api/v1/knowledge-bases/{knowledge_base_id}/files",
    "/api/v1/knowledge-bases/{knowledge_base_id}/files/{file_id}",
    "/api/v1/knowledge-bases/{knowledge_base_id}/search",
    "/api/v1/admin/members",
    "/api/v1/admin/knowledge-base-grants",
    "/api/v1/admin/knowledge-base-grants/{grant_id}",
    "/api/v1/agents/query",
    "/api/v1/files/upload",
    "/api/v1/files/attachments/{token}",
    "/api/v1/chat",
    "/api/v1/chat/{chat_id}/stream",
    "/api/v1/chats",
    "/api/v1/chats/{chat_id}",
    "/api/v1/chats/{chat_id}/messages",
    "/api/v1/documents",
    "/api/v1/dev/oidc/consent",
    "/api/v1/votes",
}


def test_openapi_exposes_every_migrated_api_path() -> None:
    paths = set(app.openapi()["paths"])

    assert EXPECTED_API_PATHS <= paths


def test_openapi_declares_bearer_security_for_business_paths() -> None:
    paths = app.openapi()["paths"]

    for path in EXPECTED_API_PATHS - {
        "/api/v1/healthz",
        "/api/v1/dev/oidc/consent",
        "/api/v1/files/attachments/{token}",
    }:
        operations = paths[path].values()
        assert all(operation.get("security") for operation in operations)


def test_openapi_includes_contract_request_models() -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert {"AgentQueryRequest", "ChatRequest", "KnowledgeBaseWriteRequest"} <= set(
        schemas
    )
