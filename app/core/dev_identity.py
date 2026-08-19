from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text

from app.core.auth import AuthenticatedUser

DEV_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
DEV_WORKSPACE_NAME = "Asianode Development Workspace"


def get_persistence_user_id(current_user: AuthenticatedUser) -> UUID:
    """Return the local UUID used to persist data for an authenticated user.

    Real users already carry a database UUID. Development identities may use
    readable subjects such as ``development-user`` or ``dev-editor-abc123``;
    those subjects are mapped to stable UUIDs server-side so they can satisfy
    the database foreign-key constraints without trusting a client-provided
    user id.
    """
    if not current_user.is_development:
        return UUID(current_user.user_id)

    if current_user.user_id == "development-user":
        return DEV_USER_ID

    try:
        return UUID(current_user.user_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"https://asianode.local/dev-user/{current_user.user_id}")


async def ensure_development_identity(
    connection: object,
    current_user: AuthenticatedUser,
    workspace_id: UUID,
) -> UUID:
    """Create the local dev user/workspace records required by chat storage."""
    if not current_user.is_development:
        return get_persistence_user_id(current_user)

    user_id = get_persistence_user_id(current_user)
    email = current_user.email or f"dev-{user_id.hex}@asianode.local"
    name = current_user.email or "Asianode Development User"

    await connection.execute(
        text(
            """
            INSERT INTO "User" (
                "id", "email", "name", "emailVerified", "isAnonymous",
                "createdAt", "updatedAt"
            )
            VALUES (
                :user_id, :email, :name, true, false,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT ("id") DO UPDATE
            SET "email" = EXCLUDED."email",
                "name" = EXCLUDED."name",
                "updatedAt" = CURRENT_TIMESTAMP
            """
        ),
        {"user_id": user_id, "email": email[:64], "name": name},
    )
    await connection.execute(
        text(
            """
            INSERT INTO "Workspace" (
                "id", "name", "ownerId", "createdAt", "updatedAt"
            )
            VALUES (
                :workspace_id, :workspace_name, :user_id,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT ("id") DO NOTHING
            """
        ),
        {
            "workspace_id": workspace_id,
            "workspace_name": DEV_WORKSPACE_NAME,
            "user_id": user_id,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO "WorkspaceMember" (
                "role", "status", "userId", "workspaceId",
                "createdAt", "updatedAt"
            )
            VALUES (
                'editor', 'active', :user_id, :workspace_id,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT ("workspaceId", "userId") DO UPDATE
            SET "status" = 'active',
                "updatedAt" = CURRENT_TIMESTAMP
            """
        ),
        {"user_id": user_id, "workspace_id": workspace_id},
    )
    return user_id
