import { readFileSync } from "node:fs";
import { expect, test } from "bun:test";

test("keeps AI review behind a parsed-document action and an open-only dialog", () => {
  const library = readFileSync(
    new URL("./knowledgeFileLibrary.tsx", import.meta.url),
    "utf8"
  );
  const review = readFileSync(
    new URL("./businessImportReview.tsx", import.meta.url),
    "utf8"
  );

  expect(library).toContain("isBusinessImportOpen");
  expect(library).toContain("onOpenChange={setIsBusinessImportOpen}");
  expect(review).toContain("shouldLoadBusinessImportJobs(isOpen)");
  expect(review).toContain("businessImportTechnicalDetails");
  expect(review).toContain("rawProviderOutput");
  expect(review).toContain("streamStages");
});
