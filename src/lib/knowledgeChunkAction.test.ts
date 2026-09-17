import { expect, test } from "bun:test";
import { getKnowledgeChunkActionLabelKey } from "./knowledgeChunkAction";

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
