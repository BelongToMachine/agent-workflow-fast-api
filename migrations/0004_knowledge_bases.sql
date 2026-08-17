-- Promote the transitional KnowledgeSource rows into an independent knowledge-base entity.
-- The legacy table remains intact for rollback and older Next.js code paths.

CREATE TABLE IF NOT EXISTS "KnowledgeBase" (
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "displayName" text NOT NULL,
    "fileHash" varchar(64),
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "sourceType" varchar(32) NOT NULL DEFAULT 'manual',
    "status" varchar(16) NOT NULL DEFAULT 'ready',
    "storageProvider" varchar(16),
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "version" integer NOT NULL DEFAULT 1,
    "workspaceId" uuid NOT NULL,
    CONSTRAINT "KnowledgeBase_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE
);

INSERT INTO "KnowledgeBase"
    (
        "createdAt", "displayName", "fileHash", "id", "sourceType", "status",
        "storageProvider", "updatedAt", "version", "workspaceId"
    )
SELECT
    source."createdAt",
    source."displayName",
    source."fileHash",
    source."id",
    source."sourceType",
    source."status",
    source."storageProvider",
    source."updatedAt",
    source."version",
    source."workspaceId"
FROM "KnowledgeSource" AS source
ON CONFLICT ("id") DO NOTHING;

CREATE INDEX IF NOT EXISTS "KnowledgeBase_workspace_status_idx"
    ON "KnowledgeBase" ("workspaceId", "status");

CREATE INDEX IF NOT EXISTS "KnowledgeBase_workspace_name_idx"
    ON "KnowledgeBase" ("workspaceId", "displayName");

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'KnowledgeBaseGrant_knowledge_base_fk'
          AND conrelid = to_regclass('public."KnowledgeBaseGrant"')
    ) THEN
        ALTER TABLE "KnowledgeBaseGrant"
            DROP CONSTRAINT "KnowledgeBaseGrant_knowledge_base_fk";
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'KnowledgeBaseGrant_knowledge_base_entity_fk'
          AND conrelid = to_regclass('public."KnowledgeBaseGrant"')
    ) THEN
        ALTER TABLE "KnowledgeBaseGrant"
            ADD CONSTRAINT "KnowledgeBaseGrant_knowledge_base_entity_fk"
            FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeBase"("id")
            ON DELETE CASCADE;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'KnowledgeFile_knowledge_base_fk'
          AND conrelid = to_regclass('public."KnowledgeFile"')
    ) THEN
        ALTER TABLE "KnowledgeFile"
            DROP CONSTRAINT "KnowledgeFile_knowledge_base_fk";
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'KnowledgeFile_knowledge_base_entity_fk'
          AND conrelid = to_regclass('public."KnowledgeFile"')
    ) THEN
        ALTER TABLE "KnowledgeFile"
            ADD CONSTRAINT "KnowledgeFile_knowledge_base_entity_fk"
            FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeBase"("id")
            ON DELETE CASCADE;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'KnowledgeChunk_knowledge_base_fk'
          AND conrelid = to_regclass('public."KnowledgeChunk"')
    ) THEN
        ALTER TABLE "KnowledgeChunk"
            DROP CONSTRAINT "KnowledgeChunk_knowledge_base_fk";
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'KnowledgeChunk_knowledge_base_entity_fk'
          AND conrelid = to_regclass('public."KnowledgeChunk"')
    ) THEN
        ALTER TABLE "KnowledgeChunk"
            ADD CONSTRAINT "KnowledgeChunk_knowledge_base_entity_fk"
            FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeBase"("id")
            ON DELETE CASCADE;
    END IF;
END $$;
