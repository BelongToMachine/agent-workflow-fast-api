-- Enforce source provenance after legacy rows have been backfilled.
--
-- This migration deliberately fails before changing nullability when any root
-- knowledge record is still missing sourceId. The foreign keys from 0007
-- already prevent orphan source references.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM "ContentRecord" WHERE "sourceId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require ContentRecord.sourceId: legacy rows still need backfill';
    END IF;

    IF EXISTS (
        SELECT 1 FROM "RealProductResearch" WHERE "sourceId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require RealProductResearch.sourceId: legacy rows still need backfill';
    END IF;

    IF EXISTS (
        SELECT 1 FROM "ProductDocument" WHERE "sourceId" IS NULL
    ) THEN
        RAISE EXCEPTION
            'Cannot require ProductDocument.sourceId: legacy rows still need backfill';
    END IF;
END $$;

ALTER TABLE "ContentRecord"
    ALTER COLUMN "sourceId" SET NOT NULL;

ALTER TABLE "RealProductResearch"
    ALTER COLUMN "sourceId" SET NOT NULL;

ALTER TABLE "ProductDocument"
    ALTER COLUMN "sourceId" SET NOT NULL;
