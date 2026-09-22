import { tool } from "ai";
import { z } from "zod";
import { logError, logEvent, summarizeToolInput } from "@/lib/ai/logger";
import { searchContent } from "@/lib/db/contentQueries";

export const createSearchContentTool = ({
  requestId,
  workspaceId,
}: {
  requestId: string;
  workspaceId: string;
}) =>
  tool({
    description:
      "Search the Asianode content operations workspace. Find content topics, copywriting, shooting plans, editing plans, and account channels by keyword, product, language, status, submitter, account, record type, or exact source file name. When the user names source files, pass them in sourceFileNames and only use records from those files; do not invent schedules or scripts.",
    execute: async (input) => {
      const startedAt = Date.now();
      logEvent("info", "tool.search_content.start", {
        input: summarizeToolInput(input),
        requestId,
      });
      try {
        const result = await searchContent(
          { ...input, workspaceId },
          requestId
        );
        logEvent("info", "tool.search_content.success", {
          durationMs: Date.now() - startedAt,
          requestId,
          resultCount: result.records.length,
          source: result.source,
        });
        return result;
      } catch (error) {
        logError("tool.search_content.error", error, {
          durationMs: Date.now() - startedAt,
          requestId,
        });
        throw error;
      }
    },
    inputSchema: z.object({
      account: z.string().optional(),
      language: z.string().optional(),
      limit: z.number().int().min(1).max(20).default(10),
      product: z.string().optional(),
      query: z.string().optional(),
      recordType: z
        .enum(["account", "copy", "edit_plan", "shoot_plan", "topic"])
        .optional(),
      sourceFileNames: z
        .array(z.string().min(1))
        .max(10)
        .describe("Exact knowledge source file names to restrict the search to")
        .optional(),
      status: z.string().optional(),
      submitter: z.string().optional(),
    }),
  });
