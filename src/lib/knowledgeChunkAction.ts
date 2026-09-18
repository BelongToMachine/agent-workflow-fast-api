export type KnowledgeChunkActionLabelKey =
  | "settings.generateKnowledgeChunks"
  | "settings.regenerateKnowledgeChunks";

export function getKnowledgeChunkDisplayStatus(
  chunkStatus: string,
  chunkCount: number,
  embeddedChunkCount: number
): string {
  return chunkStatus === "ready" &&
    chunkCount > 0 &&
    embeddedChunkCount === chunkCount
    ? "embedded"
    : chunkStatus;
}

export function getAllKnowledgeChunksEmbeddingPath(
  knowledgeBaseId: string,
  fileId: string
): string {
  return `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(fileId)}/chunks/embeddings/all`;
}

export function getKnowledgeChunkActionLabelKey(
  chunkStatus: string
): KnowledgeChunkActionLabelKey {
  return chunkStatus === "ready"
    ? "settings.regenerateKnowledgeChunks"
    : "settings.generateKnowledgeChunks";
}

export function getKnowledgeChunkSelectorKey(
  chunkStatus: string,
  chunkCount: number,
  updatedAt: string
): string {
  return JSON.stringify([chunkStatus, chunkCount, updatedAt]);
}
