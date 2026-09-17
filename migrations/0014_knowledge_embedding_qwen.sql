-- Switch the knowledge vector space to Qwen3.7 text embeddings at 1024 dimensions.
-- Existing vectors are derived data from another model/dimension and must be rebuilt.

DROP INDEX IF EXISTS "KnowledgeChunk_embedding_idx";

ALTER TABLE "KnowledgeChunk"
    ADD COLUMN IF NOT EXISTS "embeddingModel" text;

UPDATE "KnowledgeChunk"
SET "embedding" = NULL,
    "embeddingModel" = NULL;

ALTER TABLE "KnowledgeChunk"
    ALTER COLUMN "embedding" TYPE vector(1024)
    USING "embedding"::vector(1024);

CREATE INDEX IF NOT EXISTS "KnowledgeChunk_embedding_idx"
    ON "KnowledgeChunk" USING hnsw ("embedding" vector_cosine_ops)
    WHERE "embedding" IS NOT NULL;
