const activeToolStates = new Set(["input-streaming", "input-available"]);

/** @param {string} state */
export function getKnowledgeSearchTitleKey(state) {
  return activeToolStates.has(state)
    ? "chat.searchingVectorKnowledgeBase"
    : "chat.vectorKnowledgeSearch";
}
