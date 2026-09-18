import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "bun:test";
import { ParsedDocumentBlocks } from "./parsedDocumentBlocks";

describe("ParsedDocumentBlocks", () => {
  test("keeps parser blocks collapsed behind one summary by default", () => {
    const markup = renderToStaticMarkup(
      createElement(ParsedDocumentBlocks, {
        blocks: [
          {
            blockId: "block-1",
            data: { slide: 1 },
            extractionMethod: "native",
            kind: "text_box",
            locator: { slide: 1, shape: 2 },
            text: "Full parser block text",
          },
        ],
        totalBlocks: 1,
        truncated: false,
        t: (key, options) =>
          key === "settings.parsedDocumentBlockCount"
            ? `${options?.count} parsed block(s)`
            : key === "settings.parsedBlocksHeading"
              ? "Parsed content"
              : key,
      })
    );

    expect(markup).toContain("Parsed content");
    expect(markup).toContain("1 parsed block(s)");
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).toContain('data-state="closed"');
    expect(markup).not.toContain("Full parser block text");
  });

  test("shows the existing empty state when there are no parsed blocks", () => {
    const markup = renderToStaticMarkup(
      createElement(ParsedDocumentBlocks, {
        blocks: [],
        totalBlocks: 0,
        truncated: false,
        t: (key) =>
          key === "settings.noParsedBlocks"
            ? "The parser produced no text blocks."
            : key,
      })
    );

    expect(markup).toContain("The parser produced no text blocks.");
    expect(markup).not.toContain('aria-expanded=');
  });
});
