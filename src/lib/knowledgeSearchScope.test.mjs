import assert from "node:assert/strict";
import test from "node:test";
import { resolveInitialKnowledgeBaseSelection } from "./knowledgeSearchScope.mjs";

const bases = [
  { displayName: "Handbook", knowledgeBaseId: "handbook-id" },
  { displayName: "Policies", knowledgeBaseId: "policies-id" },
];

test("restores a selected base only when it is still accessible", () => {
  assert.equal(
    resolveInitialKnowledgeBaseSelection(bases, "policies-id"),
    "policies-id"
  );
  assert.equal(resolveInitialKnowledgeBaseSelection(bases, "revoked-id"), "");
});

test("selects the only accessible base and leaves multiple bases explicit", () => {
  assert.equal(
    resolveInitialKnowledgeBaseSelection([bases[0]], ""),
    "handbook-id"
  );
  assert.equal(resolveInitialKnowledgeBaseSelection(bases, ""), "");
});
