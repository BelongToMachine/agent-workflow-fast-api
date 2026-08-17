-- Optional pgvector storage for permission-filtered knowledge search.
-- Apply only after 0002_knowledge_ingestion.sql succeeds locally.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE "KnowledgeChunk"
    ADD COLUMN IF NOT EXISTS "embedding" vector(1536);

CREATE INDEX IF NOT EXISTS "KnowledgeChunk_embedding_idx"
    ON "KnowledgeChunk" USING hnsw ("embedding" vector_cosine_ops)
    WHERE "embedding" IS NOT NULL;
