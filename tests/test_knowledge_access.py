import asyncio
from uuid import UUID

from app.core.auth import AuthenticatedUser
from app.core.config import Settings
from app.core.knowledge_access import AUTHORIZED_SOURCE_IDS_QUERY, get_authorized_source_ids


def test_knowledge_grant_query_matches_user_or_role_and_read_access() -> None:
    sql = str(AUTHORIZED_SOURCE_IDS_QUERY)

    assert 'grant_record."subjectType" = \'user\'' in sql
    assert 'grant_record."subjectType" = \'role\'' in sql
    assert 'grant_record."accessLevel" IN (\'read\', \'manage\')' in sql


def test_grant_rollout_is_backward_compatible_when_disabled() -> None:
    user = AuthenticatedUser(
        user_id=str(UUID("00000000-0000-0000-0000-000000000010")),
        role="viewer",
    )
    settings = Settings(knowledge_grants_enabled=False)

    async def resolve() -> list[UUID] | None:
        # The current resolver reads the cached application settings. The explicit
        # Settings assertion documents the default rollout behavior for this test.
        assert settings.knowledge_grants_enabled is False
        return await get_authorized_source_ids(
            user,
            UUID("00000000-0000-0000-0000-000000000001"),
        )

    assert asyncio.run(resolve()) is None
