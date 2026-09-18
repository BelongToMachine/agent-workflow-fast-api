-- Review-only AI import pipeline. Agent output is persisted as proposals;
-- only a later, controlled application service can write business records.

ALTER TABLE "RealProductResearch"
    ADD COLUMN IF NOT EXISTS "sourceLocator" jsonb;
ALTER TABLE "ProductOperation"
    ADD COLUMN IF NOT EXISTS "sourceLocator" jsonb;
ALTER TABLE "ProductPrice"
    ADD COLUMN IF NOT EXISTS "sourceLocator" jsonb;
ALTER TABLE "ProductDocument"
    ADD COLUMN IF NOT EXISTS "sourceLocator" jsonb;
ALTER TABLE "ContentRecord"
    ADD COLUMN IF NOT EXISTS "sourceLocator" jsonb;

-- A PDF page or a table row may carry several independent product candidates.
-- ImportProposal is the idempotency boundary, so the legacy source-row-only
-- uniqueness would incorrectly reject valid, separately reviewed products.
DROP INDEX IF EXISTS "RealProductResearch_sourceFileId_sourceSheet_sourceRow_idx";
CREATE INDEX IF NOT EXISTS "RealProductResearch_sourceFileId_sourceSheet_sourceRow_idx"
    ON "RealProductResearch" ("sourceFileId", "sourceSheet", "sourceRow");

CREATE TABLE IF NOT EXISTS "ImportJob" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "workspaceId" uuid NOT NULL REFERENCES "public"."Workspace"("id") ON DELETE CASCADE,
    "knowledgeBaseId" uuid NOT NULL REFERENCES "public"."KnowledgeBase"("id") ON DELETE CASCADE,
    "sourceFileId" uuid NOT NULL REFERENCES "public"."KnowledgeFile"("id") ON DELETE CASCADE,
    "parsedDocumentId" uuid NOT NULL REFERENCES "public"."KnowledgeParsedDocument"("id") ON DELETE CASCADE,
    "profile" varchar(64) NOT NULL,
    "schemaVersion" varchar(64) NOT NULL,
    "promptVersion" varchar(64) NOT NULL,
    "model" varchar(128) NOT NULL,
    "status" varchar(32) NOT NULL DEFAULT 'analyzing',
    "reviewReport" jsonb,
    "rawProviderOutput" text,
    "errorMessage" text,
    "createdBy" uuid REFERENCES "public"."User"("id") ON DELETE SET NULL,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "startedAt" timestamp NOT NULL DEFAULT now(),
    "finishedAt" timestamp,
    CONSTRAINT "ImportJob_status_check"
        CHECK ("status" IN ('analyzing', 'awaiting_review', 'failed', 'applying', 'completed', 'schema_review_required', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS "ImportJob_document_updated_idx"
    ON "ImportJob" ("workspaceId", "knowledgeBaseId", "parsedDocumentId", "updatedAt" DESC);

CREATE TABLE IF NOT EXISTS "ImportProposal" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "jobId" uuid NOT NULL REFERENCES "public"."ImportJob"("id") ON DELETE CASCADE,
    "workspaceId" uuid NOT NULL REFERENCES "public"."Workspace"("id") ON DELETE CASCADE,
    "candidateRef" varchar(128) NOT NULL,
    "targetEntityType" varchar(64) NOT NULL,
    "operation" varchar(16) NOT NULL,
    "patch" jsonb NOT NULL,
    "sourceReferences" jsonb NOT NULL,
    "reviewExplanation" jsonb NOT NULL,
    "status" varchar(32) NOT NULL DEFAULT 'pending',
    "reviewComment" text,
    "reviewedBy" uuid REFERENCES "public"."User"("id") ON DELETE SET NULL,
    "reviewedAt" timestamp,
    "appliedAt" timestamp,
    "errorMessage" text,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    CONSTRAINT "ImportProposal_operation_check" CHECK ("operation" IN ('insert')),
    CONSTRAINT "ImportProposal_status_check"
        CHECK ("status" IN ('pending', 'approved', 'rejected', 'applied', 'failed', 'schema_review_required')),
    CONSTRAINT "ImportProposal_job_candidate_unique" UNIQUE ("jobId", "candidateRef")
);

CREATE INDEX IF NOT EXISTS "ImportProposal_job_status_idx"
    ON "ImportProposal" ("jobId", "status", "createdAt");

CREATE TABLE IF NOT EXISTS "ImportedFact" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "workspaceId" uuid NOT NULL REFERENCES "public"."Workspace"("id") ON DELETE CASCADE,
    "proposalId" uuid NOT NULL REFERENCES "public"."ImportProposal"("id") ON DELETE CASCADE,
    "sourceFileId" uuid NOT NULL REFERENCES "public"."KnowledgeFile"("id") ON DELETE CASCADE,
    "parsedDocumentId" uuid NOT NULL REFERENCES "public"."KnowledgeParsedDocument"("id") ON DELETE CASCADE,
    "entityType" varchar(64) NOT NULL,
    "entityId" uuid NOT NULL,
    "fieldPath" varchar(256) NOT NULL,
    "valueJson" jsonb NOT NULL,
    "blockId" varchar(128) NOT NULL,
    "dataPath" varchar(512) NOT NULL,
    "sourceLocator" jsonb NOT NULL,
    "quote" text NOT NULL,
    "status" varchar(16) NOT NULL DEFAULT 'active',
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "retiredAt" timestamp,
    CONSTRAINT "ImportedFact_status_check" CHECK ("status" IN ('active', 'superseded', 'retired'))
);

CREATE INDEX IF NOT EXISTS "ImportedFact_entity_field_idx"
    ON "ImportedFact" ("workspaceId", "entityType", "entityId", "fieldPath", "status");
CREATE INDEX IF NOT EXISTS "ImportedFact_source_idx"
    ON "ImportedFact" ("sourceFileId", "parsedDocumentId", "status");
