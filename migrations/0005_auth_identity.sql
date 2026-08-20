-- Logto external identity mapping and local user lifecycle state.
--
-- This migration deliberately keeps the existing User.id UUID unchanged. The
-- Logto subject is stored separately in ExternalIdentity so all existing
-- workspace and resource foreign keys remain valid.

ALTER TABLE "User"
    ALTER COLUMN "email" DROP NOT NULL;

ALTER TABLE "User"
    ALTER COLUMN "email" TYPE varchar(320)
    USING "email"::varchar(320);

ALTER TABLE "User"
    ADD COLUMN IF NOT EXISTS "status" varchar(16) NOT NULL DEFAULT 'active';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = to_regclass('public."User"')
          AND conname = 'User_status_check'
    ) THEN
        ALTER TABLE "User"
            ADD CONSTRAINT "User_status_check"
            CHECK ("status" IN ('active', 'suspended'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS "ExternalIdentity" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "userId" uuid NOT NULL,
    "provider" varchar(32) NOT NULL,
    "subject" varchar(255) NOT NULL,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "lastLoginAt" timestamp,
    CONSTRAINT "ExternalIdentity_user_fk"
        FOREIGN KEY ("userId") REFERENCES "public"."User"("id")
        ON DELETE CASCADE,
    CONSTRAINT "ExternalIdentity_provider_subject_key"
        UNIQUE ("provider", "subject")
);

CREATE INDEX IF NOT EXISTS "ExternalIdentity_user_idx"
    ON "ExternalIdentity" ("userId");
