-- Transitional knowledge-base grants.
-- KnowledgeSource currently represents one imported knowledge base/data source.
-- A future migration can split this into KnowledgeBase + KnowledgeBaseSource.

CREATE TABLE IF NOT EXISTS "KnowledgeBaseGrant" (
    "accessLevel" varchar(16) NOT NULL DEFAULT 'read',
    "createdAt" timestamp NOT NULL DEFAULT now(),
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "knowledgeBaseId" uuid NOT NULL,
    "subjectId" varchar(128) NOT NULL,
    "subjectType" varchar(16) NOT NULL,
    "updatedAt" timestamp NOT NULL DEFAULT now(),
    "workspaceId" uuid NOT NULL,
    CONSTRAINT "KnowledgeBaseGrant_access_level_check"
        CHECK ("accessLevel" IN ('read', 'manage')),
    CONSTRAINT "KnowledgeBaseGrant_subject_type_check"
        CHECK ("subjectType" IN ('user', 'role')),
    CONSTRAINT "KnowledgeBaseGrant_knowledge_base_fk"
        FOREIGN KEY ("knowledgeBaseId") REFERENCES "public"."KnowledgeSource"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeBaseGrant_workspace_fk"
        FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id")
        ON DELETE CASCADE,
    CONSTRAINT "KnowledgeBaseGrant_unique_subject"
        UNIQUE ("knowledgeBaseId", "subjectType", "subjectId")
);

CREATE INDEX IF NOT EXISTS "KnowledgeBaseGrant_workspace_subject_idx"
    ON "KnowledgeBaseGrant" ("workspaceId", "subjectType", "subjectId");

CREATE INDEX IF NOT EXISTS "KnowledgeBaseGrant_knowledge_base_idx"
    ON "KnowledgeBaseGrant" ("knowledgeBaseId");
