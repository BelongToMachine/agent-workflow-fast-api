import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "bun:test";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ComposerKnowledgeBaseSelector } from "./composerKnowledgeBaseSelector";

describe("ComposerKnowledgeBaseSelector", () => {
  test("renders an accessible popover trigger instead of a native dropdown", () => {
    const markup = renderToStaticMarkup(
      createElement(
        TooltipProvider,
        null,
        createElement(ComposerKnowledgeBaseSelector, {
          automaticLabel: "Automatic (assistant chooses)",
          knowledgeBases: [
            { displayName: "Sales handbook", knowledgeBaseId: "sales" },
          ],
          label: "Knowledge base",
          onChange: () => {},
          selectedKnowledgeBaseId: "sales",
        })
      )
    );

    expect(markup).toContain('aria-label="Knowledge base"');
    expect(markup).toContain('data-testid="knowledge-base-selector"');
    expect(markup).toContain('aria-haspopup="dialog"');
    expect(markup).not.toContain("<select");
    expect(markup).not.toContain("Automatic (assistant chooses)");
  });
});
