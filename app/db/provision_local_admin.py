"""Controlled development-only provisioning for the first local workspace owner."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.routes.auth_local import normalize_email
from app.core.config import get_settings
from app.core.passwords import PasswordPolicyError, hash_password
from app.db.session import get_db_connection

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

WORKSPACE_QUERY = text(
    """
    SELECT "id" AS id, "name" AS name
    FROM "Workspace"
    WHERE "id" = :workspace_id
    LIMIT 1
    FOR UPDATE
    """
)

LOCAL_ACCOUNT_QUERY = text(
    """
    SELECT user_record."id" AS user_id
    FROM "User" AS user_record
    INNER JOIN "PasswordCredential" AS credential
        ON credential."userId" = user_record."id"
    WHERE lower(btrim(user_record."email")) = :normalized_email
    LIMIT 1
    FOR UPDATE
    """
)

INSERT_USER_QUERY = text(
    """
    INSERT INTO "User" (
        "id", "email", "name", "emailVerified", "isAnonymous", "status",
        "createdAt", "updatedAt"
    )
    VALUES (
        :user_id, :email, :name, true, false, 'active',
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    """
)

INSERT_PASSWORD_CREDENTIAL_QUERY = text(
    """
    INSERT INTO "PasswordCredential" (
        "userId", "passwordHash", "passwordVersion", "passwordChangedAt",
        "createdAt", "updatedAt"
    )
    VALUES (
        :user_id, :password_hash, 1, CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    """
)

INSERT_WORKSPACE_MEMBER_QUERY = text(
    """
    INSERT INTO "WorkspaceMember" (
        "id", "role", "status", "userId", "workspaceId", "createdAt", "updatedAt"
    )
    VALUES (
        :member_id, 'owner', 'active', :user_id, :workspace_id,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    """
)

UPDATE_WORKSPACE_OWNER_QUERY = text(
    """
    UPDATE "Workspace"
    SET "ownerId" = :user_id,
        "updatedAt" = CURRENT_TIMESTAMP
    WHERE "id" = :workspace_id
    """
)

INSERT_AUTH_AUDIT_QUERY = text(
    """
    INSERT INTO "AuthAuditLog" (
        "eventType", "userId", "sessionId", "metadata"
    )
    VALUES (
        'auth.local_admin_provisioned', :user_id, NULL,
        CAST(:metadata AS jsonb)
    )
    """
)


def _read_password() -> str:
    password = getpass.getpass("New local admin password: ")
    confirmation = getpass.getpass("Confirm local admin password: ")
    if password != confirmation:
        raise PasswordPolicyError("Passwords do not match.")
    return password


async def _provision(
    *,
    email: str,
    name: str | None,
    workspace_id: UUID,
    confirmed: bool,
) -> int:
    settings = get_settings()
    if settings.environment != "development":
        print("Refusing local-admin provisioning outside ENVIRONMENT=development.")
        return 1
    if settings.auth_mode not in {"dual", "local_session"}:
        print("Set AUTH_MODE=local_session before provisioning.")
        return 1

    normalized_email = normalize_email(email)
    if not EMAIL_PATTERN.fullmatch(normalized_email):
        print("A valid email address is required.")
        return 1

    async with get_db_connection() as connection:
        async with connection.begin():
            workspace_result = await connection.execute(
                WORKSPACE_QUERY,
                {"workspace_id": workspace_id},
            )
            workspace = workspace_result.mappings().first()
            if workspace is None:
                print(f"Workspace not found: {workspace_id}")
                return 1

            account_result = await connection.execute(
                LOCAL_ACCOUNT_QUERY,
                {"normalized_email": normalized_email},
            )
            if account_result.mappings().first() is not None:
                print(f"A local account already exists for {normalized_email}.")
                return 1

            print(f"Email: {normalized_email}")
            print(f"Workspace: {workspace['name']} ({workspace_id})")
            print("Role: owner")
            if not confirmed:
                print("Preflight only. Re-run with --yes to write the account.")
                return 2

            try:
                password_hash = hash_password(_read_password())
            except PasswordPolicyError as error:
                print(f"Password rejected: {error}")
                return 1

            user_id = uuid4()
            await connection.execute(
                INSERT_USER_QUERY,
                {
                    "user_id": user_id,
                    "email": normalized_email,
                    "name": name.strip() if name and name.strip() else None,
                },
            )
            await connection.execute(
                INSERT_PASSWORD_CREDENTIAL_QUERY,
                {"user_id": user_id, "password_hash": password_hash},
            )
            await connection.execute(
                INSERT_WORKSPACE_MEMBER_QUERY,
                {
                    "member_id": uuid4(),
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                },
            )
            await connection.execute(
                UPDATE_WORKSPACE_OWNER_QUERY,
                {"user_id": user_id, "workspace_id": workspace_id},
            )
            await connection.execute(
                INSERT_AUTH_AUDIT_QUERY,
                {
                    "user_id": user_id,
                    "metadata": '{"source":"ops_command","role":"owner"}',
                },
            )

    print(f"Local workspace owner provisioned: {normalized_email}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision one local workspace owner in development only."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name")
    parser.add_argument("--workspace-id", type=UUID)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Write the account after the preflight summary and password prompt.",
    )
    args = parser.parse_args()
    settings = get_settings()
    workspace_id = args.workspace_id or settings.default_workspace_id
    try:
        exit_code = asyncio.run(
            _provision(
                email=args.email,
                name=args.name,
                workspace_id=workspace_id,
                confirmed=args.yes,
            )
        )
    except (RuntimeError, SQLAlchemyError, IntegrityError) as error:
        print(f"Provisioning failed because the database is unavailable: {error}")
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
