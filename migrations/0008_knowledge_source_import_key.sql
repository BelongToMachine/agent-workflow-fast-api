-- Make repeated source-file imports deterministic within a workspace.
-- NULL fileHash values remain allowed for legacy/manual sources.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM "KnowledgeSource"
        WHERE "fileHash" IS NOT NULL
        GROUP BY "workspaceId", "fileHash"
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot create the KnowledgeSource import key: duplicate workspace/fileHash values exist';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS "KnowledgeSource_workspace_fileHash_unique_idx"
    ON "KnowledgeSource" ("workspaceId", "fileHash")
    WHERE "fileHash" IS NOT NULL;
