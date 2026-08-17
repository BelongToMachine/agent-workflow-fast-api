import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.auth import AuthenticatedUser
from app.core.workspace_access import (
    require_workspace_permission,
    validate_workspace_context,
)

WORKSPACE_A = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_B = UUID("00000000-0000-0000-0000-000000000002")


def test_bound_token_cannot_cross_workspace_context() -> None:
    user = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        workspace_id=str(WORKSPACE_A),
    )

    with pytest.raises(HTTPException) as error:
        validate_workspace_context(user, WORKSPACE_B)

    assert error.value.status_code == 403
    assert "does not match" in str(error.value.detail)


def test_invalid_workspace_claim_is_rejected_before_database_access() -> None:
    user = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000010",
        workspace_id="not-a-uuid",
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(require_workspace_permission(user, WORKSPACE_A, "knowledge.read"))

    assert error.value.status_code == 403
    assert "invalid workspace context" in str(error.value.detail)


def test_development_identity_keeps_local_workspace_fallback() -> None:
    user = AuthenticatedUser(user_id="development-user", is_development=True)

    validate_workspace_context(user, WORKSPACE_B)
    access = asyncio.run(require_workspace_permission(user, WORKSPACE_B, "knowledge.read"))

    assert access.workspace_id == WORKSPACE_B
    assert access.is_development is True
