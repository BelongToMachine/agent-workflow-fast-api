from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.auth import AuthenticatedUser, ExternalPrincipal
from app.core.config import get_settings

LOGTO_PROVIDER = "logto"

BOOTSTRAP_USER_QUERY = text(
    """
    SELECT
        "id" AS user_id,
        "email" AS email,
        "isAnonymous" AS is_anonymous,
        "status" AS status
    FROM "User"
    WHERE "id" = :user_id
    FOR UPDATE
    """
)


class BootstrapResultError(RuntimeError):
    """Raised when the database cannot return a bootstrapped identity."""


EXTERNAL_IDENTITY_QUERY = text(
    """
    SELECT
        identity."provider" AS provider,
        identity."subject" AS subject,
        user_record."id" AS user_id,
        user_record."email" AS email,
        user_record."isAnonymous" AS is_anonymous,
        user_record."status" AS user_status
    FROM "ExternalIdentity" AS identity
    INNER JOIN "User" AS user_record
        ON user_record."id" = identity."userId"
    WHERE identity."provider" = :provider
      AND identity."subject" = :subject
    """
)


class ExternalIdentityNotInitialized(Exception):
    """Raised when a valid external identity has no local mapping yet."""


class UserSuspended(Exception):
    """Raised when the mapped local user is suspended."""


DEFAULT_WORKSPACE_QUERY = text(
    """
    SELECT "id"
    FROM "Workspace"
    WHERE "id" = :workspace_id
    """
)

DEFAULT_WORKSPACE_MEMBER_INSERT = text(
    """
    INSERT INTO "WorkspaceMember" (
        "role", "status", "userId", "workspaceId", "createdAt", "updatedAt"
    )
    VALUES (
        :role, 'active', :user_id, :workspace_id,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    ON CONFLICT ("workspaceId", "userId") DO NOTHING
    """
)


async def bootstrap_external_identity(
    connection: AsyncConnection,
    principal: ExternalPrincipal,
) -> AuthenticatedUser:
    """Create or update the local identity for one external Logto subject.

    The external subject is the only identity key. Profile claims are refreshed
    when present. Newly created users are assigned to the configured default
    workspace with the configured default role. The unique ``(provider,
    subject)`` constraint makes concurrent requests converge on a single local
    User UUID without re-granting access to an existing user whose membership
    was removed.
    """
    candidate_user_id = uuid4()
    candidate_identity_id = uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO "User" (
                "id", "email", "name", "emailVerified", "image",
                "isAnonymous", "createdAt", "updatedAt"
            )
            VALUES (
                :user_id, :email, :name, COALESCE(:email_verified, false),
                :image, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "user_id": candidate_user_id,
            "email": principal.email,
            "name": principal.name,
            "email_verified": principal.email_verified,
            "image": principal.picture,
        },
    )

    identity_result = await connection.execute(
        text(
            """
            INSERT INTO "ExternalIdentity" (
                "id", "userId", "provider", "subject", "createdAt",
                "updatedAt", "lastLoginAt"
            )
            VALUES (
                :identity_id, :user_id, :provider, :subject,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT ("provider", "subject") DO UPDATE
            SET "updatedAt" = CURRENT_TIMESTAMP,
                "lastLoginAt" = CURRENT_TIMESTAMP
            RETURNING "userId" AS user_id
            """
        ),
        {
            "identity_id": candidate_identity_id,
            "user_id": candidate_user_id,
            "provider": LOGTO_PROVIDER,
            "subject": principal.subject,
        },
    )
    identity_row = identity_result.mappings().first()
    if identity_row is None:
        raise BootstrapResultError("The external identity could not be initialized.")

    user_id = identity_row["user_id"]
    if not isinstance(user_id, UUID):
        try:
            user_id = UUID(str(user_id))
        except (TypeError, ValueError) as error:
            raise BootstrapResultError("The bootstrapped user id is invalid.") from error

    if user_id != candidate_user_id:
        await connection.execute(
            text('DELETE FROM "User" WHERE "id" = :user_id'),
            {"user_id": candidate_user_id},
        )

    user_result = await connection.execute(
        BOOTSTRAP_USER_QUERY,
        {"user_id": user_id},
    )
    user_row = user_result.mappings().first()
    if user_row is None:
        raise BootstrapResultError("The bootstrapped local user does not exist.")
    if user_row["status"] != "active":
        raise UserSuspended

    await connection.execute(
        text(
            """
            UPDATE "User"
            SET "email" = COALESCE(:email, "email"),
                "name" = COALESCE(:name, "name"),
                "emailVerified" = COALESCE(:email_verified, "emailVerified"),
                "image" = COALESCE(:image, "image"),
                "updatedAt" = CURRENT_TIMESTAMP
            WHERE "id" = :user_id
            """
        ),
        {
            "user_id": user_id,
            "email": principal.email,
            "name": principal.name,
            "email_verified": principal.email_verified,
            "image": principal.picture,
        },
    )

    if user_id == candidate_user_id:
        settings = get_settings()
        workspace_result = await connection.execute(
            DEFAULT_WORKSPACE_QUERY,
            {"workspace_id": settings.default_workspace_id},
        )
        if workspace_result.mappings().first() is None:
            raise BootstrapResultError(
                "The configured default workspace does not exist."
            )
        await connection.execute(
            DEFAULT_WORKSPACE_MEMBER_INSERT,
            {
                "role": settings.default_workspace_role,
                "user_id": user_id,
                "workspace_id": settings.default_workspace_id,
            },
        )

    return AuthenticatedUser(
        user_id=str(user_id),
        external_subject=principal.subject,
        auth_provider=LOGTO_PROVIDER,
        email=principal.email or user_row["email"],
        roles=principal.roles,
        is_guest=bool(user_row["is_anonymous"]),
        claims=principal.claims,
    )


async def resolve_external_identity(
    connection: AsyncConnection,
    principal: ExternalPrincipal,
) -> AuthenticatedUser:
    result = await connection.execute(
        EXTERNAL_IDENTITY_QUERY,
        {"provider": LOGTO_PROVIDER, "subject": principal.subject},
    )
    row = result.mappings().first()
    if row is None:
        raise ExternalIdentityNotInitialized

    if row["user_status"] != "active":
        raise UserSuspended

    return AuthenticatedUser(
        user_id=str(row["user_id"]),
        external_subject=principal.subject,
        auth_provider=LOGTO_PROVIDER,
        email=row["email"] if isinstance(row["email"], str) else None,
        roles=principal.roles,
        is_guest=bool(row["is_anonymous"]),
        claims=principal.claims,
    )
