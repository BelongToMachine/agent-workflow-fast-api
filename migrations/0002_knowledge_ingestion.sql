-- Knowledge-base file metadata and extracted text chunks.
-- KnowledgeSource remains the transitional knowledge-base entity.

CREATE TABLE IF NOT EXISTS "KnowledgeFile" (
    "byteSize" bigint NOT NULL,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "errorMessage" text,
    "fileHash" varchar(64) NOT NULL,
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "knowledgeBaseId" uuid NOT NULL,
    "mimeType" varchar(128) NOT NULL,
    "originalName" text NOT NULL,
    "status" varchar(16) NOT NULL DEFAULT 'pending',
    "storageKey" text NOT NULL,
    "storageProvider" varchar(16) NOT NULL DEFAULT 'local',
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "uploadedBy" uuid NOT NULL,
    "workspaceId" uuid NOT NULL,
    CONSTRAINT "KnowledgeFile_status_check"
        CHECK ("status" IN ('pending', 'processing', 'ready', 'failed')),
    CONSTRAINT "KnowledgeFile_knowledge_base_fk"
        FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeSource"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeFile_uploaded_by_fk"
        FOREIGN KEY ("uploadedBy") REFERENCES "public"."User"("id")
        ON DELETE RESTRICT,
    CONSTRAINT "KnowledgeFile_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeFile_unique_hash"
        UNIQUE ("knowledgeBaseId", "fileHash")
);

CREATE TABLE IF NOT EXISTS "KnowledgeChunk" (
    "chunkIndex" integer NOT NULL,
    "content" text NOT NULL,
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "fileId" uuid NOT NULL,
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "knowledgeBaseId" uuid NOT NULL,
    "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb,
    "workspaceId" uuid NOT NULL,
    CONSTRAINT "KnowledgeChunk_file_fk"
        FOREIGN KEY ("fileId") REFERENCES "public"."KnowledgeFile"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeChunk_knowledge_base_fk"
        FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeSource"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeChunk_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeChunk_file_index_unique"
        UNIQUE ("fileId", "chunkIndex")
);

CREATE INDEX IF NOT EXISTS "KnowledgeFile_workspace_idx"
    ON "KnowledgeFile" ("workspaceId", "knowledgeBaseId", "status");

CREATE INDEX IF NOT EXISTS "KnowledgeChunk_lookup_idx"
    ON "KnowledgeChunk" ("workspaceId", "knowledgeBaseId", "fileId", "chunkIndex");
