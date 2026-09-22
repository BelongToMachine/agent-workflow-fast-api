import { useState } from "react";
import { CheckIcon, DatabaseIcon, LoaderCircleIcon } from "lucide-react";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/modelSelector";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type KnowledgeBaseOption = {
  displayName: string;
  knowledgeBaseId: string;
};

const AUTOMATIC_VALUE = "__automatic__";

function isDesktopPointerDevice() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}

export function ComposerKnowledgeBaseSelector({
  automaticLabel,
  availableLabel,
  emptyMessage,
  isLoading,
  loadingLabel,
  knowledgeBases,
  label,
  onChange,
  searchPlaceholder,
  selectedKnowledgeBaseId,
}: {
  automaticLabel: string;
  availableLabel: string;
  emptyMessage: string;
  isLoading: boolean;
  loadingLabel: string;
  knowledgeBases: KnowledgeBaseOption[];
  label: string;
  onChange: (id: string) => void;
  searchPlaceholder: string;
  selectedKnowledgeBaseId: string;
}) {
  const [open, setOpen] = useState(false);
  const selectedKnowledgeBase = knowledgeBases.find(
    ({ knowledgeBaseId }) => knowledgeBaseId === selectedKnowledgeBaseId
  );
  const selectedValue = selectedKnowledgeBase
    ? `${selectedKnowledgeBase.displayName} ${selectedKnowledgeBase.knowledgeBaseId}`
    : AUTOMATIC_VALUE;

  return (
    <ModelSelector onOpenChange={setOpen} open={open}>
      <Tooltip>
        <TooltipTrigger asChild>
          <ModelSelectorTrigger asChild>
            <Button
              aria-label={label}
              className="size-11 shrink-0 rounded-lg p-0 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground active:translate-y-0 md:size-8"
              data-testid="knowledge-base-selector"
              variant="ghost"
            >
              <DatabaseIcon aria-hidden="true" className="size-4" />
            </Button>
          </ModelSelectorTrigger>
        </TooltipTrigger>
        <TooltipContent side="top" sideOffset={8}>
          {label}
        </TooltipContent>
      </Tooltip>
      <ModelSelectorContent
        commandDefaultValue={selectedValue}
        onOpenAutoFocus={(event) => {
          if (!isDesktopPointerDevice()) {
            event.preventDefault();
          }
        }}
      >
        <ModelSelectorInput placeholder={searchPlaceholder} />
        <ModelSelectorList>
          <ComposerKnowledgeBaseSelectorOptions
            automaticLabel={automaticLabel}
            availableLabel={availableLabel}
            emptyMessage={emptyMessage}
            isLoading={isLoading}
            loadingLabel={loadingLabel}
            knowledgeBases={knowledgeBases}
            onChange={onChange}
            selectedKnowledgeBaseId={selectedKnowledgeBaseId}
            onClose={() => setOpen(false)}
          />
        </ModelSelectorList>
      </ModelSelectorContent>
    </ModelSelector>
  );
}

export function ComposerKnowledgeBaseSelectorOptions({
  automaticLabel,
  availableLabel,
  emptyMessage,
  isLoading,
  loadingLabel,
  knowledgeBases,
  onChange,
  onClose,
  selectedKnowledgeBaseId,
}: {
  automaticLabel: string;
  availableLabel: string;
  emptyMessage: string;
  isLoading: boolean;
  loadingLabel: string;
  knowledgeBases: KnowledgeBaseOption[];
  onChange: (id: string) => void;
  onClose: () => void;
  selectedKnowledgeBaseId: string;
}) {
  if (isLoading) {
    return (
      <div
        aria-busy="true"
        className="flex min-h-16 items-center justify-center"
        role="status"
      >
        <LoaderCircleIcon aria-hidden="true" className="size-4 animate-spin" />
        <span className="sr-only">{loadingLabel}</span>
      </div>
    );
  }

  const selectedKnowledgeBase = knowledgeBases.find(
    ({ knowledgeBaseId }) => knowledgeBaseId === selectedKnowledgeBaseId
  );

  return (
    <>
      <ModelSelectorEmpty>{emptyMessage}</ModelSelectorEmpty>
      <ModelSelectorGroup heading={availableLabel}>
        <ModelSelectorItem
          className="data-[selected=true]:bg-muted data-[selected=true]:text-foreground"
          onSelect={() => {
            onChange("");
            onClose();
          }}
          value={AUTOMATIC_VALUE}
        >
          <CheckIcon
            aria-hidden="true"
            className={cn(
              "size-4",
              selectedKnowledgeBase ? "opacity-0" : "opacity-100"
            )}
          />
          <ModelSelectorName>{automaticLabel}</ModelSelectorName>
        </ModelSelectorItem>
        {knowledgeBases.map((knowledgeBase) => {
          const value = `${knowledgeBase.displayName} ${knowledgeBase.knowledgeBaseId}`;
          const isSelected =
            knowledgeBase.knowledgeBaseId === selectedKnowledgeBaseId;

          return (
            <ModelSelectorItem
              className="data-[selected=true]:bg-muted data-[selected=true]:text-foreground"
              key={knowledgeBase.knowledgeBaseId}
              onSelect={() => {
                onChange(knowledgeBase.knowledgeBaseId);
                onClose();
              }}
              value={value}
            >
              <CheckIcon
                aria-hidden="true"
                className={cn("size-4", isSelected ? "opacity-100" : "opacity-0")}
              />
              <ModelSelectorName>
                {knowledgeBase.displayName}
              </ModelSelectorName>
            </ModelSelectorItem>
          );
        })}
      </ModelSelectorGroup>
    </>
  );
}
