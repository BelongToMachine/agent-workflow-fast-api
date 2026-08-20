from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes.admin_knowledge_grants import (
    GRANTS_SELECT,
    UpsertKnowledgeBaseGrantRequest,
    _build_grant_view,
    _grants_disabled,
    _require_non_anonymous_development_identity,
)
from app.core.auth import AuthenticatedUser
from app.main import app

client = TestClient(app)


def test_grant_view_uses_frontend_field_names() -> None:
    view = _build_grant_view(
        {
            "grant_id": UUID("00000000-0000-0000-0000-000000000010"),
            "knowledge_base_id": UUID("00000000-0000-0000-0000-000000000011"),
            "knowledge_base_name": "Product catalog",
            "workspace_id": UUID("00000000-0000-0000-0000-000000000012"),
            "subject_type": "role",
            "subject_id": "contractor",
            "access_level": "read",
            "created_at": "2026-08-17T00:00:00Z",
            "updated_at": "2026-08-17T00:00:00Z",
        }
    )

    assert view.model_dump(by_alias=True)["knowledgeBaseId"] == (
        "00000000-0000-0000-0000-000000000011"
    )
    assert view.model_dump(by_alias=True)["subjectType"] == "role"


def test_grant_request_rejects_unknown_fields_and_empty_subjects() -> None:
    with pytest.raises(ValidationError):
        UpsertKnowledgeBaseGrantRequest.model_validate(
            {
                "accessLevel": "read",
                "knowledgeBaseId": "00000000-0000-0000-0000-000000000011",
                "subjectId": "",
                "subjectType": "role",
            }
        )

    with pytest.raises(ValidationError):
        UpsertKnowledgeBaseGrantRequest.model_validate(
            {
                "accessLevel": "read",
                "knowledgeBaseId": "00000000-0000-0000-0000-000000000011",
                "subjectId": "contractor",
                "subjectType": "role",
                "unexpected": True,
            }
        )


def test_grant_query_is_scoped_to_workspace_and_knowledge_source() -> None:
    assert 'grant_record."workspaceId" = :workspace_id' in GRANTS_SELECT
    assert 'grant_record."knowledgeBaseId"' in GRANTS_SELECT
    assert 'source."displayName" AS knowledge_base_name' in GRANTS_SELECT


def test_grant_admin_rejects_anonymous_development_identity() -> None:
    response = client.get(
        "/api/v1/admin/knowledge-base-grants",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert response.status_code == 401


def test_grant_admin_accepts_a_development_oidc_identity() -> None:
    _require_non_anonymous_development_identity(
        AuthenticatedUser(
            user_id="dev-admin",
            is_development=True,
            claims={"permissions": ["members.manage"]},
        )
    )


def test_disabled_response_explains_migration_prerequisite() -> None:
    response = _grants_disabled()

    assert response.status_code == 409
    assert response.body is not None
    assert b"Apply the FastAPI migration" in response.body
