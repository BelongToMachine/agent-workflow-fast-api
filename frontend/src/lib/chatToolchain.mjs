const agentToolTitleKeys = new Map([
  [
    "listKnowledgeBasesTool",
    ["chat.listKnowledgeBases", "chat.loadingKnowledgeBases"],
  ],
  [
    "listKnowledgeFilesTool",
    ["chat.listKnowledgeFiles", "chat.loadingKnowledgeFiles"],
  ],
  [
    "getKnowledgeBaseTool",
    ["chat.getKnowledgeBase", "chat.loadingKnowledgeBase"],
  ],
  [
    "getKnowledgeFileTool",
    ["chat.getKnowledgeFile", "chat.loadingKnowledgeFile"],
  ],
  [
    "extractKnowledgeFileTool",
    ["chat.extractKnowledgeFile", "chat.readingKnowledgeFile"],
  ],
]);

/** @param {string} toolName @param {string} state */
export function getAgentToolTitleKey(toolName, state) {
  const isActive = state === "input-streaming" || state === "input-available";
  const titleKeys = agentToolTitleKeys.get(toolName);

  if (titleKeys) {
    return titleKeys[isActive ? 1 : 0];
  }

  return isActive ? "chat.agentToolRunning" : "chat.agentToolCall";
}

/** @param {string} status */
export function isChatGenerationActive(status) {
  return status === "submitted" || status === "streaming";
}
