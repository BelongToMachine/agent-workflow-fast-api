-- Make KnowledgeFile the canonical provenance record for imported data.
--
-- KnowledgeBase remains the container and permission boundary. KnowledgeSource
-- is retained as an empty/legacy compatibility table for rollback, but new
-- records must point to KnowledgeFile through sourceFileId.

DO $$
BEGIN
    IF to_regclass('public."KnowledgeBase"') IS NULL
       OR to_regclass('public."KnowledgeFile"') IS NULL
       OR to_regclass('public."KnowledgeSource"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot migrate file provenance: KnowledgeBase, KnowledgeFile, and KnowledgeSource are required';
    END IF;
END $$;

ALTER TABLE "RealProductResearch"
    ADD COLUMN IF NOT EXISTS "sourceFileId" uuid;

ALTER TABLE "ContentRecord"
    ADD COLUMN IF NOT EXISTS "sourceFileId" uuid;

ALTER TABLE "ProductDocument"
    ADD COLUMN IF NOT EXISTS "sourceFileId" uuid;

ALTER TABLE "ProductOperation"
    ADD COLUMN IF NOT EXISTS "sourceFileId" uuid;

ALTER TABLE "ProductPrice"
    ADD COLUMN IF NOT EXISTS "sourceFileId" uuid;

-- Backfill old sourceId relationships where the old source row has a matching
-- file under the copied KnowledgeBase with the same id.
UPDATE "RealProductResearch" AS record
SET "sourceFileId" = file_record."id"
FROM "KnowledgeSource" AS legacy_source
INNER JOIN LATERAL (
    SELECT file_candidate."id"
    FROM "KnowledgeFile" AS file_candidate
    WHERE file_candidate."knowledgeBaseId" = legacy_source."id"
      AND file_candidate."workspaceId" = legacy_source."workspaceId"
      AND (
          (
              legacy_source."fileHash" IS NOT NULL
              AND file_candidate."fileHash" = legacy_source."fileHash"
          )
          OR (
              legacy_source."storageKey" IS NOT NULL
              AND file_candidate."storageKey" = legacy_source."storageKey"
          )
      )
    ORDER BY file_candidate."createdAt" DESC
    LIMIT 1
) AS file_record ON TRUE
WHERE record."sourceId" = legacy_source."id"
  AND record."sourceFileId" IS NULL;

UPDATE "ContentRecord" AS record
SET "sourceFileId" = file_record."id"
FROM "KnowledgeSource" AS legacy_source
INNER JOIN LATERAL (
    SELECT file_candidate."id"
    FROM "KnowledgeFile" AS file_candidate
    WHERE file_candidate."knowledgeBaseId" = legacy_source."id"
      AND file_candidate."workspaceId" = legacy_source."workspaceId"
      AND (
          (
              legacy_source."fileHash" IS NOT NULL
              AND file_candidate."fileHash" = legacy_source."fileHash"
          )
          OR (
              legacy_source."storageKey" IS NOT NULL
              AND file_candidate."storageKey" = legacy_source."storageKey"
          )
      )
    ORDER BY file_candidate."createdAt" DESC
    LIMIT 1
) AS file_record ON TRUE
WHERE record."sourceId" = legacy_source."id"
  AND record."sourceFileId" IS NULL;

UPDATE "ProductDocument" AS record
SET "sourceFileId" = file_record."id"
FROM "KnowledgeSource" AS legacy_source
INNER JOIN LATERAL (
    SELECT file_candidate."id"
    FROM "KnowledgeFile" AS file_candidate
    WHERE file_candidate."knowledgeBaseId" = legacy_source."id"
      AND file_candidate."workspaceId" = legacy_source."workspaceId"
      AND (
          (
              legacy_source."fileHash" IS NOT NULL
              AND file_candidate."fileHash" = legacy_source."fileHash"
          )
          OR (
              legacy_source."storageKey" IS NOT NULL
              AND file_candidate."storageKey" = legacy_source."storageKey"
          )
      )
    ORDER BY file_candidate."createdAt" DESC
    LIMIT 1
) AS file_record ON TRUE
WHERE record."sourceId" = legacy_source."id"
  AND record."sourceFileId" IS NULL;

-- Child business rows inherit the same file provenance from their research
-- record. Keeping the value on each row makes future source-file deletion
-- deterministic and avoids having to infer provenance from mutable joins.
UPDATE "ProductOperation" AS operation
SET "sourceFileId" = research."sourceFileId"
FROM "RealProductResearch" AS research
WHERE operation."researchId" = research."id"
  AND operation."sourceFileId" IS NULL;

UPDATE "ProductPrice" AS price
SET "sourceFileId" = research."sourceFileId"
FROM "RealProductResearch" AS research
WHERE price."researchId" = research."id"
  AND price."sourceFileId" IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM "RealProductResearch" WHERE "sourceFileId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require RealProductResearch.sourceFileId: legacy rows could not be matched to KnowledgeFile';
    END IF;
    IF EXISTS (
        SELECT 1 FROM "ContentRecord" WHERE "sourceFileId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require ContentRecord.sourceFileId: legacy rows could not be matched to KnowledgeFile';
    END IF;
    IF EXISTS (
        SELECT 1 FROM "ProductDocument" WHERE "sourceFileId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require ProductDocument.sourceFileId: legacy rows could not be matched to KnowledgeFile';
    END IF;
    IF EXISTS (
        SELECT 1 FROM "ProductOperation" WHERE "sourceFileId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require ProductOperation.sourceFileId: its research row has no KnowledgeFile provenance';
    END IF;
    IF EXISTS (
        SELECT 1 FROM "ProductPrice" WHERE "sourceFileId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require ProductPrice.sourceFileId: its research row has no KnowledgeFile provenance';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = to_regclass('public."RealProductResearch"')
          AND conname = 'RealProductResearch_source_file_fk'
    ) THEN
        ALTER TABLE "RealProductResearch"
            ADD CONSTRAINT "RealProductResearch_source_file_fk"
            FOREIGN KEY ("sourceFileId") REFERENCES "public"."KnowledgeFile"("id")
            ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = to_regclass('public."ContentRecord"')
          AND conname = 'ContentRecord_source_file_fk'
    ) THEN
        ALTER TABLE "ContentRecord"
            ADD CONSTRAINT "ContentRecord_source_file_fk"
            FOREIGN KEY ("sourceFileId") REFERENCES "public"."KnowledgeFile"("id")
            ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = to_regclass('public."ProductDocument"')
          AND conname = 'ProductDocument_source_file_fk'
    ) THEN
        ALTER TABLE "ProductDocument"
            ADD CONSTRAINT "ProductDocument_source_file_fk"
            FOREIGN KEY ("sourceFileId") REFERENCES "public"."KnowledgeFile"("id")
            ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = to_regclass('public."ProductOperation"')
          AND conname = 'ProductOperation_source_file_fk'
    ) THEN
        ALTER TABLE "ProductOperation"
            ADD CONSTRAINT "ProductOperation_source_file_fk"
            FOREIGN KEY ("sourceFileId") REFERENCES "public"."KnowledgeFile"("id")
            ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = to_regclass('public."ProductPrice"')
          AND conname = 'ProductPrice_source_file_fk'
    ) THEN
        ALTER TABLE "ProductPrice"
            ADD CONSTRAINT "ProductPrice_source_file_fk"
            FOREIGN KEY ("sourceFileId") REFERENCES "public"."KnowledgeFile"("id")
            ON DELETE CASCADE;
    END IF;
END $$;

ALTER TABLE "RealProductResearch" ALTER COLUMN "sourceFileId" SET NOT NULL;
ALTER TABLE "ContentRecord" ALTER COLUMN "sourceFileId" SET NOT NULL;
ALTER TABLE "ProductDocument" ALTER COLUMN "sourceFileId" SET NOT NULL;
ALTER TABLE "ProductOperation" ALTER COLUMN "sourceFileId" SET NOT NULL;
ALTER TABLE "ProductPrice" ALTER COLUMN "sourceFileId" SET NOT NULL;

-- The old column remains temporarily for rollback and old database snapshots,
-- but new writes no longer need to manufacture KnowledgeSource rows.
ALTER TABLE "ContentRecord" ALTER COLUMN "sourceId" DROP NOT NULL;
ALTER TABLE "RealProductResearch" ALTER COLUMN "sourceId" DROP NOT NULL;
ALTER TABLE "ProductDocument" ALTER COLUMN "sourceId" DROP NOT NULL;

CREATE INDEX IF NOT EXISTS "ContentRecord_sourceFileId_idx"
    ON "ContentRecord" ("sourceFileId");
CREATE INDEX IF NOT EXISTS "RealProductResearch_sourceFileId_idx"
    ON "RealProductResearch" ("sourceFileId");
CREATE INDEX IF NOT EXISTS "ProductDocument_sourceFileId_idx"
    ON "ProductDocument" ("sourceFileId");
CREATE INDEX IF NOT EXISTS "ProductOperation_sourceFileId_idx"
    ON "ProductOperation" ("sourceFileId");
CREATE INDEX IF NOT EXISTS "ProductPrice_sourceFileId_idx"
    ON "ProductPrice" ("sourceFileId");

CREATE UNIQUE INDEX IF NOT EXISTS "ContentRecord_sourceFileId_sourceSheet_sourceRow_idx"
    ON "ContentRecord" ("sourceFileId", "sourceSheet", "sourceRow");
CREATE UNIQUE INDEX IF NOT EXISTS "RealProductResearch_sourceFileId_sourceSheet_sourceRow_idx"
    ON "RealProductResearch" ("sourceFileId", "sourceSheet", "sourceRow");
