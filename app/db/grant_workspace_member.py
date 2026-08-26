"""One-time operator command for granting the first workspace owner."""

import argparse
import asyncio
import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import get_db_connection

IDENTITY_QUERY = text(
    """
    SELECT
        identity."userId" AS user_id,
        user_record."email" AS email,
        user_record."name" AS name,
        user_record."status" AS status,
        user_record."isAnonymous" AS is_anonymous
    FROM "ExternalIdentity" AS identity
    INNER JOIN "User" AS user_record
        ON user_record."id" = identity."userId"
    WHERE identity."provider" = :provider
      AND identity."subject" = :subject
    LIMIT 1
    """
)

WORKSPACE_QUERY = text(
    """
    SELECT "id" AS id, "name" AS name
    FROM "Workspace"
    WHERE "id" = :workspace_id
    LIMIT 1
    """
)

MEMBER_QUERY = text(
    """
    SELECT "id" AS member_id, "role" AS role, "status" AS status
    FROM "WorkspaceMember"
    WHERE "userId" = :user_id
      AND "workspaceId" = :workspace_id
    LIMIT 1
    """
)

ACTIVE_OWNER_QUERY = text(
    """
    SELECT "userId" AS user_id
    FROM "WorkspaceMember"
    WHERE "workspaceId" = :workspace_id
      AND "role" = 'owner'
      AND "status" = 'active'
    LIMIT 1
    """
)


async def _grant_first_owner(
    *,
    provider: str,
    subject: str,
    workspace_id: UUID,
    confirmed: bool,
) -> int:
    if not confirmed:
        print("Preflight only. Re-run with --yes to grant the first owner.")

    async with get_db_connection() as connection:
        async with connection.begin():
            identity_result = await connection.execute(
                IDENTITY_QUERY,
                {"provider": provider, "subject": subject},
            )
            identity = identity_result.mappings().first()
            if identity is None:
                print(
                    "No local user is mapped to the requested external identity. "
                    "Ask the user to sign in once before running this command."
                )
                return 1
            if identity["status"] != "active":
                print("The target local user is suspended; no owner was granted.")
                return 1
            if bool(identity["is_anonymous"]):
                print("Anonymous users cannot become workspace owners.")
                return 1

            workspace_result = await connection.execute(
                WORKSPACE_QUERY,
                {"workspace_id": workspace_id},
            )
            workspace = workspace_result.mappings().first()
            if workspace is None:
                print(f"Workspace not found: {workspace_id}")
                return 1

            member_result = await connection.execute(
                MEMBER_QUERY,
                {"user_id": identity["user_id"], "workspace_id": workspace_id},
            )
            member = member_result.mappings().first()
            if member is not None and member["role"] == "owner" and member["status"] == "active":
                print("Target user is already an active owner; no changes made.")
                return 0

            owner_result = await connection.execute(
                ACTIVE_OWNER_QUERY,
                {"workspace_id": workspace_id},
            )
            active_owner = owner_result.mappings().first()
            if active_owner is not None and active_owner["user_id"] != identity["user_id"]:
                print(
                    "An active owner already exists. This one-time command refuses to "
                    "replace or add another owner. Use the member management API instead."
                )
                return 1

            target_name = identity["name"] or identity["email"] or str(identity["user_id"])
            workspace_name = workspace["name"] or str(workspace_id)
            print(f"Target user: {target_name} ({identity['user_id']})")
            print(f"Workspace: {workspace_name} ({workspace_id})")
            print(f"Role: owner; provider: {provider}; subject: {subject}")
            if not confirmed:
                return 2

            if member is None:
                member_id = uuid4()
                await connection.execute(
                    text(
                        """
                        INSERT INTO "WorkspaceMember"
                            ("id", "role", "status", "userId", "workspaceId",
                             "createdAt", "updatedAt")
                        VALUES
                            (:member_id, 'owner', 'active', :user_id, :workspace_id,
                             CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """
                    ),
                    {
                        "member_id": member_id,
                        "user_id": identity["user_id"],
                        "workspace_id": workspace_id,
                    },
                )
                previous_role = None
                previous_status = None
            else:
                member_id = member["member_id"]
                await connection.execute(
                    text(
                        """
                        UPDATE "WorkspaceMember"
                        SET "role" = 'owner', "status" = 'active',
                            "updatedAt" = CURRENT_TIMESTAMP
                        WHERE "id" = :member_id
                        """
                    ),
                    {"member_id": member["member_id"]},
                )
                previous_role = str(member["role"])
                previous_status = str(member["status"])

            await connection.execute(
                text(
                    'DELETE FROM "WorkspaceMemberPermission" WHERE "memberId" = :member_id'
                ),
                {"member_id": member_id},
            )

            await connection.execute(
                text(
                    """
                    INSERT INTO "AuditLog"
                        ("action", "actorUserId", "metadata", "targetUserId", "workspaceId")
                    VALUES
                        (
                            'workspace.member_bootstrapped',
                            NULL,
                            CAST(:metadata AS jsonb),
                            :target_user_id,
                            :workspace_id
                        )
                    """
                ),
                {
                    "metadata": json.dumps(
                        {
                            "source": "ops_command",
                            "provider": provider,
                            "previousRole": previous_role,
                            "previousStatus": previous_status,
                            "role": "owner",
                        },
                        separators=(",", ":"),
                    ),
                    "target_user_id": identity["user_id"],
                    "workspace_id": workspace_id,
                },
            )

    print("First workspace owner granted successfully.")
    return 0


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Grant the first owner of a workspace to a bootstrapped external user."
    )
    parser.add_argument(
        "--provider",
        default="logto",
        help="External identity provider (default: logto).",
    )
    parser.add_argument(
        "--subject",
        required=True,
        help="Verified external subject, such as Logto sub.",
    )
    parser.add_argument(
        "--workspace-id",
        type=UUID,
        default=settings.default_workspace_id,
        help="Workspace UUID (defaults to ASIANODE_DEFAULT_WORKSPACE_ID).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply the change. Without this flag the command only performs a preflight.",
    )
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(
            _grant_first_owner(
                provider=args.provider,
                subject=args.subject,
                workspace_id=args.workspace_id,
                confirmed=args.yes,
            )
        )
    except IntegrityError:
        print("The membership changed concurrently; re-run the command after checking the result.")
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
