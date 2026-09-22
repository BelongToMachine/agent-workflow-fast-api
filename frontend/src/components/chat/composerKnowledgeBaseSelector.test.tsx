import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "bun:test";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  ComposerKnowledgeBaseSelector,
  ComposerKnowledgeBaseSelectorOptions,
} from "./composerKnowledgeBaseSelector";

describe("ComposerKnowledgeBaseSelector", () => {
  test("renders an accessible popover trigger instead of a native dropdown", () => {
    const markup = renderToStaticMarkup(
      createElement(
        TooltipProvider,
        null,
        createElement(ComposerKnowledgeBaseSelector, {
          automaticLabel: "Automatic (assistant chooses)",
          availableLabel: "Available",
          emptyMessage: "No matching knowledge bases",
          isLoading: false,
          loadingLabel: "Loading",
          knowledgeBases: [
            { displayName: "Sales handbook", knowledgeBaseId: "sales" },
          ],
          label: "Knowledge base",
          onChange: () => {},
          searchPlaceholder: "Search knowledge bases",
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

  test("shows a loading status while knowledge base options are pending", () => {
    const markup = renderToStaticMarkup(
      createElement(ComposerKnowledgeBaseSelectorOptions, {
        automaticLabel: "Automatic (assistant chooses)",
        availableLabel: "Available",
        emptyMessage: "No matching knowledge bases",
        isLoading: true,
        loadingLabel: "Loading knowledge bases",
        knowledgeBases: [],
        onChange: () => {},
        onClose: () => {},
        selectedKnowledgeBaseId: "",
      })
    );

    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("animate-spin");
    expect(markup).toContain("Loading knowledge bases");
    expect(markup).not.toContain("Automatic (assistant chooses)");
  });
});
