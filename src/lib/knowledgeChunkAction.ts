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
