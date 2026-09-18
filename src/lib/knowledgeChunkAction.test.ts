import { expect, test } from "bun:test";
import * as knowledgeChunkActions from "./knowledgeChunkAction";
import { i18n } from "./i18n";
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

test("a ready file is labeled embedded only when every chunk is embedded", () => {
  expect(
    knowledgeChunkActions.getKnowledgeChunkDisplayStatus?.("ready", 4, 4)
  ).toBe("embedded");
  expect(
    knowledgeChunkActions.getKnowledgeChunkDisplayStatus?.("ready", 4, 3)
  ).toBe("ready");
  expect(
    knowledgeChunkActions.getKnowledgeChunkDisplayStatus?.("ready", 0, 0)
  ).toBe("ready");
  expect(
    knowledgeChunkActions.getKnowledgeChunkDisplayStatus?.("processing", 4, 4)
  ).toBe("processing");
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

test("the all-chunks embedding path encodes file and knowledge-base IDs", () => {
  expect(
    knowledgeChunkActions.getAllKnowledgeChunksEmbeddingPath?.(
      "sales / archive",
      "file?id"
    )
  ).toBe(
    "/api/knowledge-bases/sales%20%2F%20archive/files/file%3Fid/chunks/embeddings/all"
  );
});

test("the all-chunks action has English and Chinese labels", async () => {
  await i18n.changeLanguage("zh");
  expect(i18n.t("settings.embedAllKnowledgeChunks")).toBe("向量化全部片段");
  expect(i18n.t("settings.chunkStatus.embedded")).toBe("片段已向量化");
  expect(i18n.t("settings.embeddingAllKnowledgeChunks")).toBe(
    "正在向量化全部片段…"
  );

  await i18n.changeLanguage("en");
  expect(i18n.t("settings.embedAllKnowledgeChunks")).toBe("Embed all chunks");
  expect(i18n.t("settings.chunkStatus.embedded")).toBe("Chunks embedded");
  expect(i18n.t("settings.embeddingAllKnowledgeChunks")).toBe(
    "Embedding all chunks…"
  );
});
