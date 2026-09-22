import { describe, expect, test } from "bun:test";
import * as sidebarStyles from "./sidebarStyles";

describe("sidebar navigation styles", () => {
  test("shows the selected treatment only for the active item", () => {
    const getClassName = sidebarStyles.getSidebarNavigationItemClassName;
    expect(getClassName).toBeDefined();

    const activeClassName = getClassName?.(true) ?? "";
    const inactiveClassName = getClassName?.(false) ?? "";

    expect(activeClassName).toContain("bg-sidebar-accent");
    expect(activeClassName).toContain("border-sidebar-border");
    expect(inactiveClassName).toContain("border-transparent");
    expect(inactiveClassName).not.toContain("bg-sidebar-accent ");
  });
});
