import assert from "node:assert/strict";
import test from "node:test";
import {
  getAgentToolTitleKey,
  isChatGenerationActive,
} from "./chatToolchain.mjs";

test("provides labels for backend knowledge-file tools and unknown tools", () => {
  assert.equal(
    getAgentToolTitleKey("extractKnowledgeFileTool", "output-available"),
    "chat.extractKnowledgeFile"
  );
  assert.equal(
    getAgentToolTitleKey("extractKnowledgeFileTool", "input-streaming"),
    "chat.readingKnowledgeFile"
  );
  assert.equal(
    getAgentToolTitleKey("futureAgentTool", "output-available"),
    "chat.agentToolCall"
  );
  assert.equal(
    getAgentToolTitleKey("futureAgentTool", "input-streaming"),
    "chat.agentToolRunning"
  );
});

test("keeps the chat submit control in its active state until streaming ends", () => {
  assert.equal(isChatGenerationActive("submitted"), true);
  assert.equal(isChatGenerationActive("streaming"), true);
  assert.equal(isChatGenerationActive("ready"), false);
  assert.equal(isChatGenerationActive("error"), false);
});
