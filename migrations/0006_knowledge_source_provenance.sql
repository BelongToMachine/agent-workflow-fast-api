-- Reconcile the legacy source-file table with the FastAPI migration chain.
--
-- KnowledgeSource already exists in databases created by the former frontend
-- schema. This migration is intentionally idempotent so those databases can
-- be adopted without recreating or renaming the table.

DO $$
BEGIN
    IF to_regclass('public."Workspace"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot reconcile KnowledgeSource: public."Workspace" does not exist';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS "KnowledgeSource" (
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "displayName" text NOT NULL,
    "fileHash" text,
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "sourceType" varchar(32) NOT NULL DEFAULT 'manual',
    "status" varchar(16) NOT NULL DEFAULT 'pending',
    "storageKey" text,
    "storageProvider" varchar(16),
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "version" integer NOT NULL DEFAULT 1,
    "workspaceId" uuid NOT NULL,
    CONSTRAINT "KnowledgeSource_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE
);

ALTER TABLE "KnowledgeSource"
    ADD COLUMN IF NOT EXISTS "createdAt" timestamp NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS "displayName" text,
    ADD COLUMN IF NOT EXISTS "fileHash" text,
    ADD COLUMN IF NOT EXISTS "id" uuid DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS "sourceType" varchar(32) DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS "storageKey" text,
    ADD COLUMN IF NOT EXISTS "storageProvider" varchar(16),
    ADD COLUMN IF NOT EXISTS "updatedAt" timestamp NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS "version" integer DEFAULT 1,
    ADD COLUMN IF NOT EXISTS "workspaceId" uuid;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM "KnowledgeSource"
        WHERE "displayName" IS NULL
           OR "id" IS NULL
           OR "sourceType" IS NULL
           OR "status" IS NULL
           OR "version" IS NULL
           OR "workspaceId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'KnowledgeSource contains rows with missing required provenance fields; backfill before applying 0006';
    END IF;

    ALTER TABLE "KnowledgeSource"
        ALTER COLUMN "displayName" SET NOT NULL,
        ALTER COLUMN "id" SET NOT NULL,
        ALTER COLUMN "sourceType" SET NOT NULL,
        ALTER COLUMN "status" SET NOT NULL,
        ALTER COLUMN "version" SET NOT NULL,
        ALTER COLUMN "workspaceId" SET NOT NULL;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = to_regclass('public."KnowledgeSource"')
          AND constraint_record.contype = 'p'
    ) THEN
        ALTER TABLE "KnowledgeSource"
            ADD CONSTRAINT "KnowledgeSource_pkey" PRIMARY KEY ("id");
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = to_regclass('public."KnowledgeSource"')
          AND constraint_record.contype = 'f'
          AND constraint_record.confrelid = to_regclass('public."Workspace"')
          AND constraint_record.conkey = ARRAY[
              (
                  SELECT attribute.attnum
                  FROM pg_attribute AS attribute
                  WHERE attribute.attrelid = to_regclass('public."KnowledgeSource"')
                    AND attribute.attname = 'workspaceId'
                    AND NOT attribute.attisdropped
              )
          ]::smallint[]
    ) THEN
        ALTER TABLE "KnowledgeSource"
            ADD CONSTRAINT "KnowledgeSource_workspace_fk"
            FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS "KnowledgeSource_fileHash_idx"
    ON "KnowledgeSource" ("fileHash");

CREATE INDEX IF NOT EXISTS "KnowledgeSource_workspace_status_idx"
    ON "KnowledgeSource" ("workspaceId", "status");
