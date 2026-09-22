import assert from "node:assert/strict";
import test from "node:test";
import { getKnowledgeSearchTitleKey } from "./knowledgeSearchStatus.mjs";

test("shows an active vector-search label while the tool is streaming or running", () => {
  assert.equal(
    getKnowledgeSearchTitleKey?.("input-streaming"),
    "chat.searchingVectorKnowledgeBase"
  );
  assert.equal(
    getKnowledgeSearchTitleKey?.("input-available"),
    "chat.searchingVectorKnowledgeBase"
  );
});

test("shows the vector-search tool name after it finishes or errors", () => {
  assert.equal(
    getKnowledgeSearchTitleKey?.("output-available"),
    "chat.vectorKnowledgeSearch"
  );
  assert.equal(
    getKnowledgeSearchTitleKey?.("output-error"),
    "chat.vectorKnowledgeSearch"
  );
});
