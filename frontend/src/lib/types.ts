import type { InferUITool, UIMessage } from "ai";
import { z } from "zod";
import type { ArtifactKind } from "@/components/chat/artifact";
import type { createSearchContentTool } from "./ai/tools/searchContent";
import type { createSearchProductsTool } from "./ai/tools/searchProducts";
import type { Suggestion } from "./db/schema";

export type { SourceCitation } from "./knowledgeCitation";

export const messageMetadataSchema = z.object({
  createdAt: z.string(),
});

export type MessageMetadata = z.infer<typeof messageMetadataSchema>;

type searchContentTool = InferUITool<
  ReturnType<typeof createSearchContentTool>
>;
type searchProductsTool = InferUITool<
  ReturnType<typeof createSearchProductsTool>
>;

export type ChatTools = {
  searchContentTool: searchContentTool;
  searchProductsTool: searchProductsTool;
};

export type WaitingStatusData = {
  phase: "waiting" | "still-waiting" | "health" | "thinking";
  message: string;
  modelId: string;
  modelName: string;
};

export type CustomUIDataTypes = {
  textDelta: string;
  imageDelta: string;
  sheetDelta: string;
  codeDelta: string;
  suggestion: Suggestion;
  appendMessage: string;
  id: string;
  title: string;
  kind: ArtifactKind;
  clear: null;
  finish: null;
  "chat-title": string;
  "waiting-status": WaitingStatusData;
};

export type ChatMessage = UIMessage<
  MessageMetadata,
  CustomUIDataTypes,
  ChatTools
>;

export type Attachment = {
  name: string;
  url: string;
  contentType: string;
};
