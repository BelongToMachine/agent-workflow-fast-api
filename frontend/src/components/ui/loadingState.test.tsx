import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "bun:test";
import { InlineLoadingState, LoadingState } from "./loadingState";

describe("LoadingState", () => {
  test("fills the viewport and centers its accessible loading message", () => {
    const markup = renderToStaticMarkup(
      createElement(LoadingState, { message: "Loading chat…" })
    );
    const mainClassNames = markup.match(/<main[^>]*class="([^"]+)"/)?.[1]
      .split(" ");

    expect(mainClassNames).toContain("h-dvh");
    expect(mainClassNames).toContain("w-full");
    expect(mainClassNames).toContain("items-center");
    expect(mainClassNames).toContain("justify-center");
    expect(markup).toContain('role="status"');
    expect(markup).toContain("Loading chat…");
  });

  test("can center an inline loading state across the viewport height", () => {
    const markup = renderToStaticMarkup(
      createElement(InlineLoadingState, {
        fillViewport: true,
        message: "Loading uploads…",
      })
    );
    const containerClassNames = markup.match(/<div[^>]*class="([^"]+)"/)?.[1]
      .split(" ");

    expect(containerClassNames).toContain("min-h-dvh");
    expect(containerClassNames).toContain("items-center");
    expect(containerClassNames).toContain("justify-center");
    expect(markup).toContain("Loading uploads…");
  });
});
