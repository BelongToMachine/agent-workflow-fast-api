import { expect, test } from "bun:test";
import {
  getKnowledgeChunkActionLabelKey,
  getKnowledgeChunkSelectorKey,
} from "./knowledgeChunkAction";

test("ready chunks use the regenerate action label", () => {
  expect(getKnowledgeChunkActionLabelKey("ready")).toBe(
    "settings.regenerateKnowledgeChunks"
  );
});

test("chunks that are not ready keep the generate action label", () => {
  expect(getKnowledgeChunkActionLabelKey("pending")).toBe(
    "settings.generateKnowledgeChunks"
  );
});

test("a parsed document update refreshes chunks even when their count is unchanged", () => {
  const beforeRegeneration = getKnowledgeChunkSelectorKey(
    "ready",
    4,
    "2026-09-17T09:53:00Z"
  );
  const afterRegeneration = getKnowledgeChunkSelectorKey(
    "ready",
    4,
    "2026-09-17T09:53:01Z"
  );

  expect(afterRegeneration).not.toBe(beforeRegeneration);
});
