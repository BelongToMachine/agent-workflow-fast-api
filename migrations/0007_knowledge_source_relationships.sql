-- Add source provenance relationships to legacy knowledge records.
--
-- The sourceId columns remain nullable in this migration so an older database
-- can be upgraded before the legacy rows are backfilled. Step 8 will validate
-- and tighten nullability after the backfill is complete.

DO $$
BEGIN
    IF to_regclass('public."KnowledgeSource"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot add source relationships: public."KnowledgeSource" does not exist';
    END IF;
    IF to_regclass('public."ContentRecord"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot add source relationships: public."ContentRecord" does not exist';
    END IF;
    IF to_regclass('public."RealProductResearch"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot add source relationships: public."RealProductResearch" does not exist';
    END IF;
    IF to_regclass('public."ProductDocument"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot add source relationships: public."ProductDocument" does not exist';
    END IF;
END $$;

ALTER TABLE "ContentRecord"
    ADD COLUMN IF NOT EXISTS "sourceId" uuid;

ALTER TABLE "RealProductResearch"
    ADD COLUMN IF NOT EXISTS "sourceId" uuid;

ALTER TABLE "ProductDocument"
    ADD COLUMN IF NOT EXISTS "sourceId" uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = to_regclass('public."ContentRecord"')
          AND constraint_record.contype = 'f'
          AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
          AND constraint_record.conkey = ARRAY[
              (
                  SELECT attribute.attnum
                  FROM pg_attribute AS attribute
                  WHERE attribute.attrelid = to_regclass('public."ContentRecord"')
                    AND attribute.attname = 'sourceId'
                    AND NOT attribute.attisdropped
              )
          ]::smallint[]
    ) THEN
        ALTER TABLE "ContentRecord"
            ADD CONSTRAINT "ContentRecord_source_fk"
            FOREIGN KEY ("sourceId") REFERENCES "public"."KnowledgeSource"("id")
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = to_regclass('public."RealProductResearch"')
          AND constraint_record.contype = 'f'
          AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
          AND constraint_record.conkey = ARRAY[
              (
                  SELECT attribute.attnum
                  FROM pg_attribute AS attribute
                  WHERE attribute.attrelid = to_regclass('public."RealProductResearch"')
                    AND attribute.attname = 'sourceId'
                    AND NOT attribute.attisdropped
              )
          ]::smallint[]
    ) THEN
        ALTER TABLE "RealProductResearch"
            ADD CONSTRAINT "RealProductResearch_source_fk"
            FOREIGN KEY ("sourceId") REFERENCES "public"."KnowledgeSource"("id")
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.conrelid = to_regclass('public."ProductDocument"')
          AND constraint_record.contype = 'f'
          AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
          AND constraint_record.conkey = ARRAY[
              (
                  SELECT attribute.attnum
                  FROM pg_attribute AS attribute
                  WHERE attribute.attrelid = to_regclass('public."ProductDocument"')
                    AND attribute.attname = 'sourceId'
                    AND NOT attribute.attisdropped
              )
          ]::smallint[]
    ) THEN
        ALTER TABLE "ProductDocument"
            ADD CONSTRAINT "ProductDocument_source_fk"
            FOREIGN KEY ("sourceId") REFERENCES "public"."KnowledgeSource"("id")
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS "ContentRecord_sourceId_idx"
    ON "ContentRecord" ("sourceId");

CREATE INDEX IF NOT EXISTS "RealProductResearch_sourceId_idx"
    ON "RealProductResearch" ("sourceId");

CREATE INDEX IF NOT EXISTS "ProductDocument_sourceId_idx"
    ON "ProductDocument" ("sourceId");

-- The old indexes made sheet/row coordinates globally unique. Scope them by
-- source so two files may legitimately contain the same worksheet and row.
DROP INDEX IF EXISTS "ContentRecord_sourceSheet_sourceRow_idx";
DROP INDEX IF EXISTS "RealProductResearch_sourceSheet_sourceRow_idx";

CREATE UNIQUE INDEX IF NOT EXISTS "ContentRecord_sourceId_sourceSheet_sourceRow_idx"
    ON "ContentRecord" ("sourceId", "sourceSheet", "sourceRow");

CREATE UNIQUE INDEX IF NOT EXISTS "RealProductResearch_sourceId_sourceSheet_sourceRow_idx"
    ON "RealProductResearch" ("sourceId", "sourceSheet", "sourceRow");
