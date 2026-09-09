-- Local authentication foundations.
--
-- This migration is additive. It does not migrate legacy Logto users or
-- ExternalIdentity rows; those records may remain temporarily while the
-- service is validated in dual-auth mode before local sessions become the
-- only authentication method.

CREATE TABLE IF NOT EXISTS "PasswordCredential" (
    "userId" uuid PRIMARY KEY,
    "passwordHash" text NOT NULL,
    "passwordVersion" integer NOT NULL DEFAULT 1,
    "passwordChangedAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PasswordCredential_user_fk"
        FOREIGN KEY ("userId") REFERENCES "public"."User"("id")
        ON DELETE CASCADE,
    CONSTRAINT "PasswordCredential_version_check"
        CHECK ("passwordVersion" >= 1)
);

CREATE TABLE IF NOT EXISTS "AuthSession" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "userId" uuid NOT NULL,
    "tokenHash" char(64) UNIQUE NOT NULL,
    "createdAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeenAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "idleExpiresAt" timestamp NOT NULL,
    "absoluteExpiresAt" timestamp NOT NULL,
    "revokedAt" timestamp,
    "ipHash" char(64),
    "userAgentHash" char(64),
    CONSTRAINT "AuthSession_user_fk"
        FOREIGN KEY ("userId") REFERENCES "public"."User"("id")
        ON DELETE CASCADE,
    CONSTRAINT "AuthSession_expiry_check"
        CHECK ("idleExpiresAt" <= "absoluteExpiresAt")
);

CREATE INDEX IF NOT EXISTS "AuthSession_user_active_idx"
    ON "AuthSession" ("userId", "revokedAt", "absoluteExpiresAt");

CREATE TABLE IF NOT EXISTS "AuthOneTimeToken" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "userId" uuid,
    "normalizedEmail" varchar(320) NOT NULL,
    "purpose" varchar(32) NOT NULL,
    "tokenHash" char(64) UNIQUE NOT NULL,
    "workspaceId" uuid,
    "workspaceRole" varchar(16),
    "expiresAt" timestamp NOT NULL,
    "usedAt" timestamp,
    "revokedAt" timestamp,
    "createdBy" uuid,
    "createdAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AuthOneTimeToken_user_fk"
        FOREIGN KEY ("userId") REFERENCES "public"."User"("id")
        ON DELETE CASCADE,
    CONSTRAINT "AuthOneTimeToken_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE,
    CONSTRAINT "AuthOneTimeToken_created_by_fk"
        FOREIGN KEY ("createdBy") REFERENCES "public"."User"("id")
        ON DELETE SET NULL,
    CONSTRAINT "AuthOneTimeToken_purpose_check"
        CHECK ("purpose" IN ('invitation', 'password_reset', 'email_verification'))
);

CREATE INDEX IF NOT EXISTS "AuthOneTimeToken_user_purpose_idx"
    ON "AuthOneTimeToken" ("userId", "purpose", "expiresAt");

CREATE INDEX IF NOT EXISTS "AuthOneTimeToken_email_purpose_idx"
    ON "AuthOneTimeToken" ("normalizedEmail", "purpose", "expiresAt");

CREATE TABLE IF NOT EXISTS "AuthAuditLog" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "eventType" varchar(64) NOT NULL,
    "userId" uuid,
    "sessionId" uuid,
    "ipHash" char(64),
    "userAgentHash" char(64),
    "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb,
    "createdAt" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AuthAuditLog_user_fk"
        FOREIGN KEY ("userId") REFERENCES "public"."User"("id")
        ON DELETE SET NULL,
    CONSTRAINT "AuthAuditLog_session_fk"
        FOREIGN KEY ("sessionId") REFERENCES "public"."AuthSession"("id")
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS "AuthAuditLog_user_created_idx"
    ON "AuthAuditLog" ("userId", "createdAt");

CREATE INDEX IF NOT EXISTS "AuthAuditLog_event_created_idx"
    ON "AuthAuditLog" ("eventType", "createdAt");
