"use client";
import type { UseChatHelpers } from "@ai-sdk/react";
import type { SourceCitation } from "@/lib/knowledgeCitation";
import type { ChatMessage } from "@/lib/types";
import { cn, hasToolControlSyntax, sanitizeText } from "@/lib/utils";
import { MessageContent, MessageResponse } from "../ai-elements/message";
import { Shimmer } from "../ai-elements/shimmer";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "../ai-elements/tool";
import { useDataStream } from "./dataStreamProvider";
import { SparklesIcon } from "./icons";
import { MessageActions } from "./messageActions";
import { MessageReasoning } from "./messageReasoning";
import { PreviewAttachment } from "./previewAttachment";

function WaitingText() {
  const { waitingStatus } = useDataStream();
  const waitingText = waitingStatus?.message ?? "Waiting...";

  return (
    <div className="flex min-h-[calc(13px*1.65)] min-w-0 items-center text-[13px] leading-[1.65]">
      <Shimmer
        as="span"
        className="font-medium whitespace-normal break-words"
        duration={1}
      >
        {waitingText}
      </Shimmer>
    </div>
  );
}

function SourceCitationLine({
  citation,
  fileName,
  row,
  sheet,
}: {
  citation?: SourceCitation | null;
  fileName?: string | null;
  row?: number | null;
  sheet?: string | null;
}) {
  const resolvedFileName = citation?.fileName ?? fileName;
  const resolvedSheet = citation?.sheet ?? sheet;
  const resolvedRow = citation?.row ?? row;
  const location = [
    resolvedSheet,
    resolvedRow === undefined || resolvedRow === null
      ? null
      : `第 ${resolvedRow} 行`,
    citation?.page === undefined || citation.page === null
      ? null
      : `第 ${citation.page} 页`,
    citation?.section,
  ].filter(Boolean);

  if (!resolvedFileName && location.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 border-border/50 border-t pt-2 text-muted-foreground text-xs">
      来源：{resolvedFileName ?? "文件名未知"}
      {location.length > 0 ? ` · ${location.join(" · ")}` : ""}
    </div>
  );
}

const PurePreviewMessage = ({
  addToolApprovalResponse: _addToolApprovalResponse,
  message,
  isLoading,
  setMessages: _setMessages,
  regenerate: _regenerate,
  isReadonly,
  requiresScrollPadding: _requiresScrollPadding,
  onEdit,
}: {
  addToolApprovalResponse: UseChatHelpers<ChatMessage>["addToolApprovalResponse"];
  message: ChatMessage;
  isLoading: boolean;
  setMessages: UseChatHelpers<ChatMessage>["setMessages"];
  regenerate: UseChatHelpers<ChatMessage>["regenerate"];
  isReadonly: boolean;
  requiresScrollPadding: boolean;
  onEdit?: (message: ChatMessage) => void;
}) => {
  const attachmentsFromMessage = message.parts.filter(
    (part) => part.type === "file"
  );

  useDataStream();

  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  const hasAnyContent = message.parts?.some(
    (part) =>
      (part.type === "text" && part.text?.trim().length > 0) ||
      (part.type === "reasoning" &&
        "text" in part &&
        part.text?.trim().length > 0) ||
      part.type.startsWith("tool-")
  );
  const isThinking = isAssistant && isLoading && !hasAnyContent;

  const attachments = attachmentsFromMessage.length > 0 && (
    <div
      className="flex flex-row justify-end gap-2"
      data-testid={"message-attachments"}
    >
      {attachmentsFromMessage.map((attachment) => (
        <PreviewAttachment
          attachment={{
            contentType: attachment.mediaType,
            name: attachment.filename ?? "file",
            url: attachment.url,
          }}
          key={attachment.url}
        />
      ))}
    </div>
  );

  const mergedReasoning = message.parts?.reduce(
    (acc, part) => {
      if (part.type === "reasoning" && part.text?.trim().length > 0) {
        return {
          isStreaming: "state" in part ? part.state === "streaming" : false,
          rendered: false,
          text: acc.text ? `${acc.text}\n\n${part.text}` : part.text,
        };
      }
      return acc;
    },
    { isStreaming: false, rendered: false, text: "" }
  ) ?? { isStreaming: false, rendered: false, text: "" };

  const dynamicToolCounts = new Map<string, number>();
  const dynamicToolLastCallIds = new Map<string, string>();
  message.parts?.forEach((part) => {
    if (part.type !== "dynamic-tool") {
      return;
    }

    dynamicToolCounts.set(
      part.toolName,
      (dynamicToolCounts.get(part.toolName) ?? 0) + 1
    );
    dynamicToolLastCallIds.set(part.toolName, part.toolCallId);
  });

  const displayParts = [
    ...(message.parts?.filter((part) => part.type === "dynamic-tool") ?? []),
    ...(message.parts?.filter((part) => part.type !== "dynamic-tool") ?? []),
  ];

  const parts = displayParts.map((part, index) => {
    const { type } = part;
    const key = `message-${message.id}-part-${index}`;

    if (type === "reasoning") {
      if (!mergedReasoning.rendered && mergedReasoning.text) {
        mergedReasoning.rendered = true;
        return (
          <MessageReasoning
            isLoading={isLoading || mergedReasoning.isStreaming}
            key={key}
            reasoning={mergedReasoning.text}
          />
        );
      }
      return null;
    }

    if (type === "text") {
      const sanitizedText = sanitizeText(part.text);
      const isHiddenToolText =
        hasToolControlSyntax(part.text) && !sanitizedText.trim();

      if (isHiddenToolText) {
        return (
          <MessageContent
            className="text-[13px] leading-[1.65] text-muted-foreground"
            data-testid="message-tool-recovery"
            key={key}
          >
            本次工具调用未完成，请重新发送问题。
          </MessageContent>
        );
      }

      return (
        <MessageContent
          className={cn("text-[13px] leading-[1.65]", {
            "w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-2xl rounded-br-lg border border-border/30 bg-gradient-to-br from-secondary to-muted px-3.5 py-2 shadow-[var(--shadow-card)]":
              message.role === "user",
          })}
          data-testid="message-content"
          key={key}
        >
          <MessageResponse>{sanitizedText}</MessageResponse>
        </MessageContent>
      );
    }

    if (type === "dynamic-tool" && part.toolName === "searchProductsTool") {
      if (dynamicToolLastCallIds.get(part.toolName) !== part.toolCallId) {
        return null;
      }

      const { toolCallId, state } = part;
      const toolCallCount = dynamicToolCounts.get(part.toolName) ?? 1;
      const output =
        state === "output-available" &&
        part.output &&
        typeof part.output === "object"
          ? (part.output as {
              products?: Array<{
                productId: string;
                nameEn: string;
                nameZh?: string | null;
                category: string;
                unitPriceUsd?: string | null;
                moqUnits?: number | null;
                leadTimeDays?: number | null;
                supplierName: string;
                supplierCity?: string | null;
                supplierQualityRating?: string | null;
                priceCurrency?: string | null;
                priceMin?: string | null;
                priceMax?: string | null;
                priceSummary?: string | null;
                operationStatus?: string | null;
                promotionStatus?: string | null;
                proposer?: string | null;
                logisticsTerm?: string | null;
                qualifications?: string | null;
                hasDocuments?: boolean;
                documentCount?: number;
                sourceFileName?: string | null;
                sourceId?: string | null;
                sourceSheet?: string;
                sourceRow?: number;
                citation?: SourceCitation;
              }>;
              source?: string;
              sourceTable?: string;
              message?: string;
            })
          : null;

      return (
        <Tool
          className="w-[min(100%,650px)]"
          defaultOpen={false}
          key={toolCallId}
        >
          <ToolHeader
            state={state}
            title={`Search products${toolCallCount > 1 ? ` · ${toolCallCount} steps` : ""}`}
            toolName="searchProductsTool"
            type="dynamic-tool"
          />
          <ToolContent>
            {state === "input-available" && <ToolInput input={part.input} />}
            {state === "output-available" && output && (
              <div className="space-y-3">
                <div className="text-muted-foreground text-xs">
                  {output.products?.length ?? 0} products found
                  {output.source ? ` · ${output.source}` : ""}
                </div>
                <div className="grid gap-2">
                  {output.products?.map((product) => (
                    <div
                      className="rounded-md border bg-muted/30 p-3 text-sm"
                      key={product.productId}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="font-medium">{product.nameEn}</div>
                          {!!product.nameZh && (
                            <div className="text-muted-foreground text-xs">
                              {product.nameZh}
                            </div>
                          )}
                        </div>
                        <div className="max-w-[45%] text-right font-medium text-xs">
                          {product.priceSummary ??
                            (product.unitPriceUsd
                              ? `$${product.unitPriceUsd}`
                              : "—")}
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground text-xs">
                        <span>{product.productId}</span>
                        <span>{product.supplierName}</span>
                        <span>MOQ {product.moqUnits ?? "—"}</span>
                        <span>{product.leadTimeDays ?? "—"} days</span>
                        {!!product.operationStatus && (
                          <span>{product.operationStatus}</span>
                        )}
                        {!!product.logisticsTerm && (
                          <span>{product.logisticsTerm}</span>
                        )}
                        {!!product.hasDocuments && (
                          <span>{product.documentCount ?? 0} docs</span>
                        )}
                      </div>
                      <SourceCitationLine
                        citation={product.citation}
                        fileName={product.sourceFileName}
                        row={product.sourceRow}
                        sheet={product.sourceSheet}
                      />
                    </div>
                  ))}
                </div>
                {!!output.message && (
                  <div className="text-muted-foreground text-xs">
                    {output.message}
                  </div>
                )}
              </div>
            )}
            {state === "output-error" && (
              <ToolOutput errorText={part.errorText} output={undefined} />
            )}
          </ToolContent>
        </Tool>
      );
    }

    if (type === "dynamic-tool" && part.toolName === "searchContentTool") {
      if (dynamicToolLastCallIds.get(part.toolName) !== part.toolCallId) {
        return null;
      }

      const { toolCallId, state } = part;
      const toolCallCount = dynamicToolCounts.get(part.toolName) ?? 1;
      const output =
        state === "output-available" &&
        part.output &&
        typeof part.output === "object"
          ? (part.output as {
              message?: string;
              records?: Array<{
                copyText?: string | null;
                language?: string | null;
                plannedAt?: string | null;
                product?: string | null;
                recordType: string;
                reviewStatus?: string | null;
                sourceRow: number;
                sourceSheet: string;
                sourceFileName?: string | null;
                sourceId?: string | null;
                submitter?: string | null;
                targetTopic?: string | null;
                usageStatus?: string | null;
                videoType?: string | null;
                citation?: SourceCitation;
              }>;
              source?: string;
            })
          : null;

      return (
        <Tool
          className="w-[min(100%,650px)]"
          defaultOpen={false}
          key={toolCallId}
        >
          <ToolHeader
            state={state}
            title={`Search content operations${toolCallCount > 1 ? ` · ${toolCallCount} steps` : ""}`}
            toolName="searchContentTool"
            type="dynamic-tool"
          />
          <ToolContent>
            {state === "input-available" && <ToolInput input={part.input} />}
            {state === "output-available" && output && (
              <div className="space-y-3">
                <div className="text-muted-foreground text-xs">
                  {output.records?.length ?? 0} content records found
                  {output.source ? ` · ${output.source}` : ""}
                </div>
                <div className="grid gap-2">
                  {output.records?.map((record) => (
                    <div
                      className="rounded-md border bg-muted/30 p-3 text-sm"
                      key={`${record.sourceSheet}-${record.sourceRow}`}
                    >
                      <div className="font-medium">
                        {record.product ?? record.targetTopic ?? "未命名内容"}
                      </div>
                      {!!record.copyText && (
                        <div className="mt-1 line-clamp-3 text-muted-foreground text-xs">
                          {record.copyText}
                        </div>
                      )}
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground text-xs">
                        <span>{record.recordType}</span>
                        {!!record.videoType && <span>{record.videoType}</span>}
                        {!!record.language && <span>{record.language}</span>}
                        {!!record.submitter && <span>{record.submitter}</span>}
                        {!!record.reviewStatus && (
                          <span>{record.reviewStatus}</span>
                        )}
                        {!!record.usageStatus && (
                          <span>{record.usageStatus}</span>
                        )}
                        {!!record.plannedAt && (
                          <span>
                            {new Date(record.plannedAt).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                      <SourceCitationLine
                        citation={record.citation}
                        fileName={record.sourceFileName}
                        row={record.sourceRow}
                        sheet={record.sourceSheet}
                      />
                    </div>
                  ))}
                </div>
                {!!output.message && (
                  <div className="text-muted-foreground text-xs">
                    {output.message}
                  </div>
                )}
              </div>
            )}
            {state === "output-error" && (
              <ToolOutput errorText={part.errorText} output={undefined} />
            )}
          </ToolContent>
        </Tool>
      );
    }

    return null;
  });

  const actions = !isReadonly && (
    <MessageActions
      isLoading={isLoading}
      key={`action-${message.id}`}
      message={message}
      onEdit={onEdit ? () => onEdit(message) : undefined}
    />
  );

  const content = isThinking ? (
    <WaitingText />
  ) : (
    <>
      {attachments}
      {parts}
      {actions}
    </>
  );

  return (
    <div
      className={cn(
        "group/message w-full",
        !isAssistant && "animate-[fade-up_0.25s_cubic-bezier(0.22,1,0.36,1)]"
      )}
      data-role={message.role}
      data-testid={`message-${message.role}`}
    >
      <div
        className={cn(
          isUser ? "flex flex-col items-end gap-2" : "flex items-start gap-3"
        )}
      >
        {isAssistant && (
          <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
            <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
              <SparklesIcon size={13} />
            </div>
          </div>
        )}
        {isAssistant ? (
          <div className="flex min-w-0 flex-1 flex-col gap-2">{content}</div>
        ) : (
          content
        )}
      </div>
    </div>
  );
};

export const PreviewMessage = PurePreviewMessage;

export const ThinkingMessage = () => (
  <div
    className="group/message w-full"
    data-role="assistant"
    data-testid="message-assistant-loading"
  >
    <div className="flex items-start gap-3">
      <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
        <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
          <SparklesIcon size={13} />
        </div>
      </div>

      <WaitingText />
    </div>
  </div>
);
