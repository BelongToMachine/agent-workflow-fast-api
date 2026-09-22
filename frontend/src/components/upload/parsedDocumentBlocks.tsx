"use client";

import { useId, useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export type ParsedDocumentBlock = {
  blockId: string;
  data?: unknown;
  extractionMethod: string;
  kind: string;
  locator: Record<string, string | number>;
  text: string;
};

type Props = {
  blocks: ParsedDocumentBlock[];
  totalBlocks: number | null;
  truncated: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
};

function formatLocator(locator: ParsedDocumentBlock["locator"]) {
  return Object.entries(locator)
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
}

export function ParsedDocumentBlocks({
  blocks,
  totalBlocks,
  truncated,
  t,
}: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const contentId = useId();

  if (blocks.length === 0) {
    return (
      <div className="space-y-3 p-4">
        <p className="rounded-xl border border-dashed border-border/80 px-4 py-8 text-center text-muted-foreground text-sm">
          {t("settings.noParsedBlocks")}
        </p>
        {truncated ? (
          <p className="text-muted-foreground text-xs">
            {t("settings.parsedDocumentTruncated", {
              count: totalBlocks ?? blocks.length,
            })}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <section className="mx-4 mb-4 overflow-hidden rounded-xl border border-border/70 bg-card/30">
      <Collapsible onOpenChange={setIsExpanded} open={isExpanded}>
        <CollapsibleTrigger asChild>
          <Button
            aria-controls={contentId}
            aria-expanded={isExpanded}
            className="h-auto w-full justify-between rounded-none px-4 py-3 text-left hover:bg-muted/50"
            data-testid="parsed-document-blocks-trigger"
            variant="ghost"
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="font-medium text-sm">
                {t("settings.parsedBlocksHeading")}
              </span>
              <Badge variant="outline">
                {t("settings.parsedDocumentBlockCount", {
                  count: blocks.length,
                })}
              </Badge>
            </span>
            <ChevronDownIcon
              aria-hidden="true"
              className={cn(
                "shrink-0 transition-transform duration-200",
                isExpanded && "rotate-180"
              )}
            />
          </Button>
        </CollapsibleTrigger>

        <CollapsibleContent id={contentId}>
          <div className="border-t border-border/70 px-4">
            <div className="divide-y divide-border/70">
              {blocks.map((block, index) => (
                <article className="py-4" key={block.blockId}>
                  <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
                    <Badge variant="outline">{block.kind}</Badge>
                    <span>{block.extractionMethod}</span>
                    <span>#{index + 1}</span>
                    <span>{formatLocator(block.locator)}</span>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                    {block.text}
                  </p>
                  {block.data !== undefined && block.data !== null ? (
                    <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-muted/70 p-3 text-xs leading-5">
                      {JSON.stringify(block.data, null, 2)}
                    </pre>
                  ) : null}
                </article>
              ))}
            </div>
            {truncated ? (
              <p className="border-t border-border/70 py-3 text-muted-foreground text-xs">
                {t("settings.parsedDocumentTruncated", {
                  count: totalBlocks ?? blocks.length,
                })}
              </p>
            ) : null}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
