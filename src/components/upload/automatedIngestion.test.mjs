import assert from "node:assert/strict";
import test from "node:test";

let waitForAutomatedIngestion;
try {
  ({ waitForAutomatedIngestion } = await import("./automatedIngestion.mjs"));
} catch {
  // Keep the red-phase failure specific to the missing workflow behavior.
}

test("tracks parsing, chunking, and embedding until all chunks are ready", async () => {
  assert.equal(
    typeof waitForAutomatedIngestion,
    "function",
    "automated ingestion polling should be implemented"
  );

  const knowledgeBaseId = "knowledge base/1";
  const fileId = "file-1";
  const fileStates = ["processing", "ready", "ready", "ready", "ready"];
  const parsedStates = ["pending", "processing", "ready", "ready"];
  const chunkStates = [
    { items: [{ isEmbedded: false }], total: 1 },
    { items: [{ isEmbedded: true }], total: 1 },
  ];
  const requestedPaths = [];
  const stages = [];

  const result = await waitForAutomatedIngestion({
    fileId,
    knowledgeBaseId,
    onStage: (stage) => stages.push(stage),
    request: async (path) => {
      requestedPaths.push(path);
      if (path.endsWith("/files")) {
        return {
          files: [
            {
              errorMessage: null,
              fileId,
              status: fileStates.shift(),
            },
          ],
        };
      }
      if (path.endsWith("/parsed-document")) {
        const chunkStatus = parsedStates.shift();
        return {
          chunkCount: chunkStatus === "ready" ? 4 : 0,
          chunkStatus,
          parsedDocumentId: "parsed-1",
        };
      }
      return chunkStates.shift() ?? chunkStates.at(-1);
    },
    sleep: async () => {},
    intervalMs: 0,
    maxAttempts: 5,
  });

  assert.deepEqual(stages, [
    "parsing",
    "chunking",
    "chunking",
    "embedding",
    "embedding",
    "complete",
  ]);
  assert.equal(result.parsedDocument.chunkCount, 4);
  assert.equal(result.chunks.items[0].isEmbedded, true);
  assert.deepEqual(requestedPaths.slice(0, 3), [
    "/api/knowledge-bases/knowledge%20base%2F1/files",
    "/api/knowledge-bases/knowledge%20base%2F1/files",
    "/api/knowledge-bases/knowledge%20base%2F1/files/file-1/parsed-document",
  ]);
  assert.ok(
    requestedPaths.some(
      (path) =>
        path === "/api/knowledge-bases/knowledge%20base%2F1/files/file-1/chunks"
    )
  );
});

test("stops polling and reports the backend error when parsing fails", async () => {
  assert.equal(
    typeof waitForAutomatedIngestion,
    "function",
    "automated ingestion polling should be implemented"
  );

  let parsedDocumentRequested = false;
  await assert.rejects(
    waitForAutomatedIngestion({
      fileId: "file-1",
      knowledgeBaseId: "knowledge-base-1",
      request: async (path) => {
        if (path.endsWith("/files")) {
          return {
            files: [
              {
                errorMessage: "The document could not be parsed.",
                fileId: "file-1",
                status: "failed",
              },
            ],
          };
        }
        parsedDocumentRequested = true;
        return {};
      },
      sleep: async () => {},
      intervalMs: 0,
      maxAttempts: 2,
    }),
    /could not be parsed/
  );
  assert.equal(parsedDocumentRequested, false);
});

test("stops before chunk polling when the backend reports a chunk failure", async () => {
  const stages = [];
  await assert.rejects(
    waitForAutomatedIngestion({
      fileId: "file-1",
      knowledgeBaseId: "knowledge-base-1",
      onStage: (stage) => stages.push(stage),
      request: async (path) => {
        if (path.endsWith("/files")) {
          return {
            files: [{ fileId: "file-1", status: "ready" }],
          };
        }
        if (path.endsWith("/parsed-document")) {
          return {
            chunkCount: 1,
            chunkErrorMessage: "Embedding provider failed.",
            chunkStatus: "failed",
          };
        }
        throw new Error("chunks should not be loaded after a failure");
      },
      sleep: async () => {},
      intervalMs: 0,
      maxAttempts: 2,
    }),
    /Embedding provider failed/
  );
  assert.deepEqual(stages, []);
});
