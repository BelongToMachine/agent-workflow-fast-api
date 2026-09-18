import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "bun:test";
import { LoadingState } from "./loadingState";

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
});
