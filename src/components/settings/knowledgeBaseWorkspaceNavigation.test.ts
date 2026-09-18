import { describe, expect, test } from "bun:test";
import { getKnowledgeBaseWorkspaceSection } from "./knowledgeBaseWorkspaceNavigation";

describe("knowledge base workspace route compatibility", () => {
  test("keeps the existing authorization URL on the access section", () => {
    expect(getKnowledgeBaseWorkspaceSection("/settings/knowledge-bases")).toBe(
      "access"
    );
  });

  test("keeps the existing knowledge base URL on the management section", () => {
    expect(
      getKnowledgeBaseWorkspaceSection("/settings/knowledge-bases/files/")
    ).toBe("management");
  });
});
