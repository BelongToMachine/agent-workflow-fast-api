/**
 * @param {Array<{ knowledgeBaseId: string }>} knowledgeBases
 * @param {string | null | undefined} storedSelection
 */
export function resolveInitialKnowledgeBaseSelection(
  knowledgeBases,
  storedSelection
) {
  const accessibleIds = new Set(
    knowledgeBases.map(({ knowledgeBaseId }) => knowledgeBaseId)
  );

  if (storedSelection && accessibleIds.has(storedSelection)) {
    return storedSelection;
  }
  return knowledgeBases.length === 1
    ? knowledgeBases[0].knowledgeBaseId
    : "";
}
