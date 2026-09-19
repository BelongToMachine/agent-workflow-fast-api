function delay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The operation was aborted.", "AbortError"));
      return;
    }

    const timeoutId = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    const abort = () => {
      clearTimeout(timeoutId);
      reject(new DOMException("The operation was aborted.", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/**
 * @param {{
 *   fileId: string;
 *   intervalMs?: number;
 *   knowledgeBaseId: string;
 *   maxAttempts?: number;
 *   onStage?: (stage: "parsing" | "chunking" | "embedding" | "complete") => void;
 *   request: (path: string, init?: RequestInit) => Promise<Record<string, any>>;
 *   signal?: AbortSignal;
 *   sleep?: (milliseconds: number) => Promise<void>;
 *   timeoutMessage?: string;
 * }} options
 * @returns {Promise<{
 *   file: { fileId: string; [key: string]: any };
 *   parsedDocument: { parsedDocumentId: string; chunkCount: number; [key: string]: any };
 *   chunks: { items: Array<{ isEmbedded: boolean; [key: string]: any }>; total: number; [key: string]: any };
 * }>}
 */
export async function waitForAutomatedIngestion({
  fileId,
  intervalMs = 1200,
  knowledgeBaseId,
  maxAttempts = 240,
  onStage = () => {},
  request,
  signal,
  sleep = (milliseconds) => delay(milliseconds, signal),
  timeoutMessage = "Document processing took too long.",
}) {
  const encodedKnowledgeBaseId = encodeURIComponent(knowledgeBaseId);
  const encodedFileId = encodeURIComponent(fileId);
  const filesPath = `/api/knowledge-bases/${encodedKnowledgeBaseId}/files`;
  const parsedDocumentPath = `${filesPath}/${encodedFileId}/parsed-document`;
  const chunksPath = `${filesPath}/${encodedFileId}/chunks`;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const { files } = await request(filesPath, { signal });
    const file = files.find((candidate) => candidate.fileId === fileId);
    if (!file) {
      throw new Error("The uploaded file is no longer available.");
    }
    if (file.status === "failed") {
      throw new Error(file.errorMessage || "The document could not be parsed.");
    }
    if (file.status !== "ready") {
      onStage("parsing");
      await sleep(intervalMs);
      continue;
    }

    let parsedDocument;
    try {
      parsedDocument = await request(parsedDocumentPath, { signal });
    } catch (error) {
      if (error?.status === 404) {
        onStage("parsing");
        await sleep(intervalMs);
        continue;
      }
      throw error;
    }

    if (parsedDocument.chunkStatus === "failed") {
      throw new Error(
        parsedDocument.chunkErrorMessage || "Knowledge chunks could not be created."
      );
    }
    if (parsedDocument.chunkStatus === "ready") {
      onStage("embedding");
      let chunks = await request(chunksPath, { signal });
      const chunkItems = [...(chunks.items ?? [])];
      while (chunks.nextOffset !== null && chunks.nextOffset !== undefined) {
        chunks = await request(
          `${chunksPath}?offset=${encodeURIComponent(chunks.nextOffset)}`,
          { signal }
        );
        chunkItems.push(...(chunks.items ?? []));
      }
      const allChunks = { ...chunks, items: chunkItems };
      const allChunksEmbedded =
        allChunks.total === 0 ||
        (chunkItems.length >= allChunks.total &&
          chunkItems.every((chunk) => chunk.isEmbedded));
      if (allChunksEmbedded) {
        onStage("complete");
        return { file, parsedDocument, chunks: allChunks };
      }
      await sleep(intervalMs);
      continue;
    }

    onStage("chunking");
    await sleep(intervalMs);
  }

  throw new Error(timeoutMessage);
}
