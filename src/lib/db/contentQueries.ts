import "server-only";

import { and, asc, eq, ilike, inArray, or } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import { logError, logEvent } from "@/lib/ai/logger";
import type { SourceCitation } from "@/lib/knowledgeCitation";
import { isMockDatabase } from "../constants";
import { contentRecord, knowledgeFile } from "./schema";

const db = isMockDatabase
  ? (undefined as never)
  : drizzle(postgres(process.env.POSTGRES_URL ?? ""));

export type SearchContentInput = {
  account?: string;
  language?: string;
  limit?: number;
  product?: string;
  query?: string;
  recordType?: "account" | "copy" | "edit_plan" | "shoot_plan" | "topic";
  sourceFileNames?: string[];
  status?: string;
  submitter?: string;
  workspaceId?: string;
};

type ContentSearchResult = {
  accountDirection: string | null;
  accountName: string | null;
  accountType: string | null;
  aiMaterials: string | null;
  attachment: string | null;
  copyText: string | null;
  copyWriter: string | null;
  language: string | null;
  notes: string | null;
  photographer: string | null;
  platform: string | null;
  plannedAt: string | null;
  product: string | null;
  recordType: string;
  referenceVideo: string | null;
  revisedCopy: string | null;
  reviewStatus: string | null;
  scriptDocument: string | null;
  searchText: string;
  shootConfirmed: string | null;
  shootingScene: string | null;
  sourceRow: number;
  sourceSheet: string;
  sourceId: string | null;
  sourceFileName: string | null;
  submitter: string | null;
  tags: string | null;
  targetTopic: string | null;
  title: string | null;
  usageStatus: string | null;
  videoType: string | null;
  citation: SourceCitation;
};

type SearchContentResponse = {
  records: ContentSearchResult[];
  source: "enterprise" | "mock";
  sourceTable?: "ContentRecord";
  message?: string;
};

const resultLimit = (limit?: number) => Math.min(Math.max(limit ?? 10, 1), 20);
const textPattern = (value: string) => `%${value.trim()}%`;
const normalizedSourceFileNames = (values?: string[]) => [
  ...new Set(values?.map((value) => value.trim()).filter(Boolean) ?? []),
];

export async function searchContent(
  input: SearchContentInput,
  requestId?: string
): Promise<SearchContentResponse> {
  if (isMockDatabase) {
    return {
      message: "Content data is not loaded in mock mode.",
      records: [],
      source: "mock",
    };
  }

  if (!input.workspaceId) {
    return {
      message: "Workspace context is required for knowledge-base queries.",
      records: [],
      source: "enterprise",
      sourceTable: "ContentRecord",
    };
  }

  const sourceFileNames = normalizedSourceFileNames(input.sourceFileNames);
  let sourceFileIds: string[] | undefined;
  let missingSourceFileNames: string[] = [];

  if (sourceFileNames.length > 0) {
    const sourceRows = await db
      .select({
        displayName: knowledgeFile.originalName,
        id: knowledgeFile.id,
      })
      .from(knowledgeFile)
      .where(
        and(
          eq(knowledgeFile.status, "ready"),
          eq(knowledgeFile.workspaceId, input.workspaceId),
          inArray(knowledgeFile.originalName, sourceFileNames)
        )
      );
    const foundSourceNames = new Set(
      sourceRows.map(({ displayName }) => displayName)
    );
    missingSourceFileNames = sourceFileNames.filter(
      (fileName) => !foundSourceNames.has(fileName)
    );
    const matchedFileIds = sourceRows.map(({ id }) => id);
    sourceFileIds = matchedFileIds;

    if (matchedFileIds.length === 0) {
      return {
        message: `No knowledge file matched: ${sourceFileNames.join(", ")}`,
        records: [],
        source: "enterprise",
        sourceTable: "ContentRecord",
      };
    }
  }

  const search = input.query?.trim();
  const conditions = [
    eq(knowledgeFile.workspaceId, input.workspaceId),
    sourceFileIds ? inArray(contentRecord.sourceFileId, sourceFileIds) : undefined,
    input.account
      ? or(
          ilike(contentRecord.accountName, textPattern(input.account)),
          ilike(contentRecord.accountType, textPattern(input.account)),
          ilike(contentRecord.accountDirection, textPattern(input.account))
        )
      : undefined,
    input.language
      ? ilike(contentRecord.language, textPattern(input.language))
      : undefined,
    input.product
      ? ilike(contentRecord.product, textPattern(input.product))
      : undefined,
    input.recordType
      ? eq(contentRecord.recordType, input.recordType)
      : undefined,
    input.status
      ? or(
          ilike(contentRecord.reviewStatus, textPattern(input.status)),
          ilike(contentRecord.usageStatus, textPattern(input.status)),
          ilike(contentRecord.shootConfirmed, textPattern(input.status))
        )
      : undefined,
    input.submitter
      ? or(
          ilike(contentRecord.submitter, textPattern(input.submitter)),
          ilike(contentRecord.copyWriter, textPattern(input.submitter)),
          ilike(contentRecord.photographer, textPattern(input.submitter))
        )
      : undefined,
    search ? ilike(contentRecord.searchText, textPattern(search)) : undefined,
  ].filter(Boolean);

  const startedAt = Date.now();
  logEvent("info", "db.search_content.start", { requestId });

  return db
    .select({
      accountDirection: contentRecord.accountDirection,
      accountName: contentRecord.accountName,
      accountType: contentRecord.accountType,
      aiMaterials: contentRecord.aiMaterials,
      attachment: contentRecord.attachment,
      copyText: contentRecord.copyText,
      copyWriter: contentRecord.copyWriter,
      language: contentRecord.language,
      notes: contentRecord.notes,
      photographer: contentRecord.photographer,
      plannedAt: contentRecord.plannedAt,
      platform: contentRecord.platform,
      product: contentRecord.product,
      recordType: contentRecord.recordType,
      referenceVideo: contentRecord.referenceVideo,
      reviewStatus: contentRecord.reviewStatus,
      revisedCopy: contentRecord.revisedCopy,
      scriptDocument: contentRecord.scriptDocument,
      searchText: contentRecord.searchText,
      shootConfirmed: contentRecord.shootConfirmed,
      shootingScene: contentRecord.shootingScene,
      sourceFileName: knowledgeFile.originalName,
      sourceId: contentRecord.sourceFileId,
      sourceRow: contentRecord.sourceRow,
      sourceSheet: contentRecord.sourceSheet,
      submitter: contentRecord.submitter,
      tags: contentRecord.tags,
      targetTopic: contentRecord.targetTopic,
      title: contentRecord.title,
      usageStatus: contentRecord.usageStatus,
      videoType: contentRecord.videoType,
    })
    .from(contentRecord)
    .leftJoin(knowledgeFile, eq(contentRecord.sourceFileId, knowledgeFile.id))
    .where(and(...conditions))
    .orderBy(asc(contentRecord.plannedAt), asc(contentRecord.sourceRow))
    .limit(resultLimit(input.limit))
    .then((records) => {
      logEvent("info", "db.search_content.success", {
        durationMs: Date.now() - startedAt,
        requestId,
        resultCount: records.length,
      });
      return {
        ...(missingSourceFileNames.length > 0
          ? {
              message: `Source files not found: ${missingSourceFileNames.join(", ")}`,
            }
          : {}),
        records: records.map((record) => ({
          ...record,
          citation: {
            fileName: record.sourceFileName,
            row: record.sourceRow,
            sheet: record.sourceSheet,
            sourceId: record.sourceId,
          },
          // Tool outputs must be JSON values. Drizzle returns timestamp
          // columns as Date instances, which fail AI SDK prompt validation
          // when the result is fed into the next agent step.
          plannedAt: record.plannedAt?.toISOString() ?? null,
        })),
        source: "enterprise" as const,
        sourceTable: "ContentRecord" as const,
      };
    })
    .catch((error) => {
      logError("db.search_content.error", error, {
        durationMs: Date.now() - startedAt,
        requestId,
      });
      throw error;
    });
}
