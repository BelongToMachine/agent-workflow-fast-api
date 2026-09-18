"use client";

import { useTranslation } from "react-i18next";
import { KnowledgeBaseGrants } from "@/components/settings/knowledgeBaseGrants";
import { KnowledgeBaseManagement } from "@/components/settings/knowledgeBaseManagement";
import { Link, usePathname } from "@/lib/router";
import { cn } from "@/lib/utils";
import { getKnowledgeBaseWorkspaceSection } from "./knowledgeBaseWorkspaceNavigation";

export function KnowledgeBaseWorkspace() {
  const { t } = useTranslation();
  const activeSection = getKnowledgeBaseWorkspaceSection(usePathname());

  return (
    <div className="flex flex-col gap-6">
      <nav
        aria-label={t("settings.knowledgeBases")}
        className="flex w-fit max-w-full flex-wrap gap-1 rounded-2xl border border-border/70 bg-muted/30 p-1"
      >
        <Link
          aria-current={activeSection === "management" ? "page" : undefined}
          className={cn(
            "inline-flex min-h-10 items-center justify-center rounded-xl px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            activeSection === "management"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:bg-background/70 hover:text-foreground"
          )}
          href="/settings/knowledge-bases/files"
        >
          {t("settings.knowledgeBaseManagement")}
        </Link>
        <Link
          aria-current={activeSection === "access" ? "page" : undefined}
          className={cn(
            "inline-flex min-h-10 items-center justify-center rounded-xl px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            activeSection === "access"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:bg-background/70 hover:text-foreground"
          )}
          href="/settings/knowledge-bases"
        >
          {t("settings.knowledgeBaseAccess")}
        </Link>
      </nav>

      {activeSection === "management" ? (
        <KnowledgeBaseManagement />
      ) : (
        <KnowledgeBaseGrants />
      )}
    </div>
  );
}
