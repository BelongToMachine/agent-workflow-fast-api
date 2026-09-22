import { tool } from "ai";
import { z } from "zod";
import { logError, logEvent, summarizeToolInput } from "@/lib/ai/logger";
import { searchProducts } from "@/lib/db/tradeQueries";

export const createSearchProductsTool = ({
  requestId,
  workspaceId,
}: {
  requestId: string;
  workspaceId: string;
}) =>
  tool({
    description:
      "Search the active Asianode enterprise product research and operations data. Supports product keywords, category, price, lead time, MOQ, promotion status, sales channel, proposer, logistics, qualification, document presence, missing-field filters, and exact source file names. When the user names source files, pass them in sourceFileNames and only use products from those files.",
    execute: async (input) => {
      const startedAt = Date.now();
      logEvent("info", "tool.search_products.start", {
        input: summarizeToolInput(input),
        requestId,
      });
      try {
        const result = await searchProducts(
          { ...input, workspaceId },
          requestId
        );
        logEvent("info", "tool.search_products.success", {
          durationMs: Date.now() - startedAt,
          requestId,
          resultCount: result.products.length,
          source: result.source,
        });
        return result;
      } catch (error) {
        logError("tool.search_products.error", error, {
          durationMs: Date.now() - startedAt,
          requestId,
        });
        throw error;
      }
    },
    inputSchema: z.object({
      category: z
        .string()
        .describe("Exact product category when known")
        .optional(),
      hasDocument: z.boolean().optional(),
      limit: z.number().int().min(1).max(20).default(10),
      logistics: z.string().optional(),
      maxLeadDays: z.number().int().positive().optional(),
      maxMoqUnits: z.number().int().positive().optional(),
      maxPriceUsd: z.number().nonnegative().optional(),
      missingField: z
        .enum([
          "price",
          "supplier",
          "qualification",
          "document",
          "promotionStatus",
        ])
        .describe("Find products missing a structured business field")
        .optional(),
      operationStatus: z
        .string()
        .describe("Operation status such as promoted, not_promoted, or review")
        .optional(),
      proposer: z.string().optional(),
      qualification: z.string().optional(),
      query: z
        .string()
        .describe("Product keyword or natural-language category hint")
        .optional(),
      sourceFileNames: z
        .array(z.string().min(1))
        .max(10)
        .describe("Exact knowledge source file names to restrict the search to")
        .optional(),
      targetChannel: z.string().optional(),
    }),
  });
