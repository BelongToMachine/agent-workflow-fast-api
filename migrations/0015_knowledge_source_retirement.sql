-- Retire KnowledgeSource after all business records have canonical KnowledgeFile
-- provenance. The legacy sourceId values are redundant and are removed only
-- after validating every required sourceFileId relationship.

DO $$
DECLARE
    expected_relationship RECORD;
BEGIN
    IF to_regclass('public."KnowledgeSource"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot retire KnowledgeSource: the legacy table is unexpectedly absent';
    END IF;

    IF to_regclass('public."KnowledgeBase"') IS NULL
       OR to_regclass('public."KnowledgeFile"') IS NULL THEN
        RAISE EXCEPTION
            'Cannot retire KnowledgeSource: KnowledgeBase and KnowledgeFile are required';
    END IF;

    FOR expected_relationship IN
        SELECT * FROM (VALUES
            ('ContentRecord', 'ContentRecord_source_file_fk'),
            ('RealProductResearch', 'RealProductResearch_source_file_fk'),
            ('ProductDocument', 'ProductDocument_source_file_fk'),
            ('ProductOperation', 'ProductOperation_source_file_fk'),
            ('ProductPrice', 'ProductPrice_source_file_fk')
        ) AS expected(table_name, constraint_name)
    LOOP
        IF to_regclass(format('public.%I', expected_relationship.table_name)) IS NULL
           OR NOT EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = expected_relationship.table_name
                 AND column_name = 'sourceFileId'
                 AND is_nullable = 'NO'
           )
           OR NOT EXISTS (
               SELECT 1
               FROM pg_constraint AS constraint_record
               WHERE constraint_record.conrelid = to_regclass(
                         format('public.%I', expected_relationship.table_name)
                     )
                 AND constraint_record.conname = expected_relationship.constraint_name
                 AND constraint_record.contype = 'f'
                 AND constraint_record.confrelid = to_regclass('public."KnowledgeFile"')
                 AND constraint_record.convalidated
           ) THEN
            RAISE EXCEPTION
                'Cannot retire KnowledgeSource: %.sourceFileId must be required and reference KnowledgeFile',
                expected_relationship.table_name;
        END IF;
    END LOOP;

    -- Do not silently drop any dependency that has not been migrated to
    -- sourceFileId. Only the three known legacy sourceId foreign keys are safe.
    IF EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_record
        WHERE constraint_record.contype = 'f'
          AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
          AND NOT (
              (
                  constraint_record.conrelid = to_regclass('public."ContentRecord"')
                  AND constraint_record.conkey = ARRAY[(
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."ContentRecord"')
                        AND attribute.attname = 'sourceId'
                        AND NOT attribute.attisdropped
                  )]::smallint[]
              )
              OR (
                  constraint_record.conrelid = to_regclass('public."RealProductResearch"')
                  AND constraint_record.conkey = ARRAY[(
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."RealProductResearch"')
                        AND attribute.attname = 'sourceId'
                        AND NOT attribute.attisdropped
                  )]::smallint[]
              )
              OR (
                  constraint_record.conrelid = to_regclass('public."ProductDocument"')
                  AND constraint_record.conkey = ARRAY[(
                      SELECT attribute.attnum
                      FROM pg_attribute AS attribute
                      WHERE attribute.attrelid = to_regclass('public."ProductDocument"')
                        AND attribute.attname = 'sourceId'
                        AND NOT attribute.attisdropped
                  )]::smallint[]
              )
          )
    ) THEN
        RAISE EXCEPTION
            'Cannot retire KnowledgeSource: unexpected foreign key references exist outside the known sourceId relationships';
    END IF;
END $$;

DO $$
DECLARE
    legacy_relationship RECORD;
BEGIN
    FOR legacy_relationship IN
        SELECT
            relation_record.relname AS table_name,
            constraint_record.conname AS constraint_name
        FROM pg_constraint AS constraint_record
        INNER JOIN pg_class AS relation_record
            ON relation_record.oid = constraint_record.conrelid
        WHERE constraint_record.contype = 'f'
          AND constraint_record.confrelid = to_regclass('public."KnowledgeSource"')
          AND constraint_record.conrelid IN (
              to_regclass('public."ContentRecord"'),
              to_regclass('public."RealProductResearch"'),
              to_regclass('public."ProductDocument"')
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE %I DROP CONSTRAINT %I',
            legacy_relationship.table_name,
            legacy_relationship.constraint_name
        );
    END LOOP;
END $$;

DROP INDEX IF EXISTS "ContentRecord_sourceId_idx";
DROP INDEX IF EXISTS "ContentRecord_sourceId_sourceSheet_sourceRow_idx";
DROP INDEX IF EXISTS "RealProductResearch_sourceId_idx";
DROP INDEX IF EXISTS "RealProductResearch_sourceId_sourceSheet_sourceRow_idx";
DROP INDEX IF EXISTS "ProductDocument_sourceId_idx";

ALTER TABLE "ContentRecord" DROP COLUMN IF EXISTS "sourceId";
ALTER TABLE "RealProductResearch" DROP COLUMN IF EXISTS "sourceId";
ALTER TABLE "ProductDocument" DROP COLUMN IF EXISTS "sourceId";

DROP TABLE "KnowledgeSource";
