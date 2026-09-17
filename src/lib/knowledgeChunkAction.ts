export type KnowledgeChunkActionLabelKey =
  | "settings.generateKnowledgeChunks"
  | "settings.regenerateKnowledgeChunks";

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
