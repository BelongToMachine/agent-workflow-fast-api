export type KnowledgeBaseWorkspaceSection = "access" | "management";

const KNOWLEDGE_BASES_PATH = "/settings/knowledge-bases";

export function getKnowledgeBaseWorkspaceSection(
  pathname: string
): KnowledgeBaseWorkspaceSection {
  const normalizedPathname = pathname.replace(/\/+$/, "") || "/";

  return normalizedPathname === KNOWLEDGE_BASES_PATH ? "access" : "management";
}
