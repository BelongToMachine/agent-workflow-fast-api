-- Persist the deterministic parser output as a reviewable intermediate artifact.
--
-- KnowledgeFile remains the original object in local/S3 storage. This table
-- stores the ParsedDocument JSON that was produced from that object. Chunk
-- materialization is intentionally tracked separately and is not performed by
-- the file parser.

CREATE TABLE IF NOT EXISTS "KnowledgeParsedDocument" (
    "blockCount" integer NOT NULL,
    "chunkErrorMessage" text,
    "chunkStatus" varchar(16) NOT NULL DEFAULT 'pending',
    "chunkedAt" timestamp,
    "contentType" varchar(16) NOT NULL,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "document" jsonb NOT NULL,
    "fileHash" varchar(64) NOT NULL,
    "fileId" uuid NOT NULL,
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "knowledgeBaseId" uuid NOT NULL,
    "parser" varchar(64) NOT NULL,
    "parserVersion" varchar(32) NOT NULL,
    "schemaVersion" varchar(64) NOT NULL,
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "warningCount" integer NOT NULL DEFAULT 0,
    "workspaceId" uuid NOT NULL,
    CONSTRAINT "KnowledgeParsedDocument_chunk_status_check"
        CHECK ("chunkStatus" IN ('pending', 'processing', 'ready', 'failed')),
    CONSTRAINT "KnowledgeParsedDocument_file_unique"
        UNIQUE ("fileId"),
    CONSTRAINT "KnowledgeParsedDocument_file_fk"
        FOREIGN KEY ("fileId") REFERENCES "public"."KnowledgeFile"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeParsedDocument_knowledge_base_fk"
        FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeBase"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeParsedDocument_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS "KnowledgeParsedDocument_lookup_idx"
    ON "KnowledgeParsedDocument" ("workspaceId", "knowledgeBaseId", "updatedAt");
