import assert from "node:assert/strict";
import test from "node:test";

let waitForAutomatedIngestion;
try {
  ({ waitForAutomatedIngestion } = await import("./automatedIngestion.mjs"));
} catch {
  // Keep the red-phase failure specific to the missing workflow behavior.
}

test("tracks parsing and chunking separately until both are ready", async () => {
  assert.equal(
    typeof waitForAutomatedIngestion,
    "function",
    "automated ingestion polling should be implemented"
  );

  const knowledgeBaseId = "knowledge base/1";
  const fileId = "file-1";
  const fileStates = ["processing", "ready", "ready", "ready"];
  const chunkStates = ["pending", "processing", "ready"];
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
      return {
        chunkCount: chunkStates.at(-1) === "ready" ? 4 : 0,
        chunkStatus: chunkStates.shift(),
      };
    },
    sleep: async () => {},
    intervalMs: 0,
    maxAttempts: 5,
  });

  assert.deepEqual(stages, ["parsing", "chunking", "chunking", "complete"]);
  assert.equal(result.parsedDocument.chunkCount, 4);
  assert.deepEqual(requestedPaths.slice(0, 3), [
    "/api/knowledge-bases/knowledge%20base%2F1/files",
    "/api/knowledge-bases/knowledge%20base%2F1/files",
    "/api/knowledge-bases/knowledge%20base%2F1/files/file-1/parsed-document",
  ]);
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
