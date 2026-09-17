import "server-only";

import { and, asc, eq, ilike, inArray, or } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import { logError, logEvent } from "@/lib/ai/logger";
import type { SourceCitation } from "@/lib/knowledgeCitation";
import { isMockDatabase } from "../constants";
import {
  knowledgeFile,
  productDocument,
  productOperation,
  productPrice,
  realProductResearch,
} from "./schema";

const db = isMockDatabase
  ? (undefined as never)
  : drizzle(postgres(process.env.POSTGRES_URL ?? ""));

export type SearchProductsInput = {
  query?: string;
  category?: string;
  maxPriceUsd?: number;
  maxLeadDays?: number;
  maxMoqUnits?: number;
  operationStatus?: string;
  targetChannel?: string;
  proposer?: string;
  logistics?: string;
  qualification?: string;
  hasDocument?: boolean;
  missingField?:
    | "price"
    | "supplier"
    | "qualification"
    | "document"
    | "promotionStatus";
  limit?: number;
  sourceFileNames?: string[];
  workspaceId?: string;
};

type ProductSearchResult = {
  productId: string;
  sku?: string | null;
  nameEn: string;
  nameZh?: string | null;
  nameTr?: string | null;
  category: string;
  material?: string | null;
  unitPriceUsd?: string | null;
  moqUnits?: number | null;
  leadTimeDays?: number | null;
  customization?: string | null;
  sampleAvailable?: boolean | null;
  supplierId?: string | null;
  supplierName: string;
  supplierCity?: string | null;
  supplierQualityRating?: string | null;
  priceMin?: string | null;
  priceMax?: string | null;
  priceCurrency?: string | null;
  priceSummary?: string | null;
  operationStatus?: string | null;
  promotionStatus?: string | null;
  proposer?: string | null;
  logisticsTerm?: string | null;
  qualifications?: string | null;
  hasDocuments?: boolean;
  documentCount?: number;
  sourceId?: string | null;
  sourceFileName?: string | null;
  sourceSheet?: string;
  sourceRow?: number;
  citation: SourceCitation;
};

type ProductSearchResponse = {
  products: ProductSearchResult[];
  source: "enterprise" | "mock";
  sourceTable?: "RealProductResearch" | "RealProductResearch + operations";
  message?: string;
};

const resultLimit = (limit?: number) => Math.min(Math.max(limit ?? 10, 1), 50);

const textPattern = (value: string) => `%${value.trim()}%`;
const normalizedSourceFileNames = (values?: string[]) => [
  ...new Set(values?.map((value) => value.trim()).filter(Boolean) ?? []),
];

function normalizeOperationStatusFilter(value: string) {
  const normalized = value.trim().toLowerCase();
  const aliases: Record<string, string> = {
    上会调研: "review",
    否: "not_promoted",
    已推广: "promoted",
    是: "promoted",
    未推广: "not_promoted",
    调研: "review",
  };
  return aliases[normalized] ?? normalized;
}

function extractLeadDays(value: string | null | undefined) {
  if (!value) {
    return null;
  }

  const days = [...value.matchAll(/(\d+(?:\.\d+)?)\s*(?:days?|日|天)/gi)]
    .map((match) => Number(match[1]))
    .filter(Number.isFinite);

  return days.length > 0 ? Math.max(...days) : null;
}

async function searchEnterpriseProducts(
  input: SearchProductsInput
): Promise<ProductSearchResponse> {
  if (!input.workspaceId) {
    return {
      message: "Workspace context is required for product queries.",
      products: [],
      source: "enterprise",
      sourceTable: "RealProductResearch + operations",
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
        products: [],
        source: "enterprise",
        sourceTable: "RealProductResearch + operations",
      };
    }
  }

  if (input.maxMoqUnits !== undefined) {
    return {
      message:
        "The enterprise dataset does not contain a structured MOQ field, so the MOQ filter was not applied and no products were returned.",
      products: [],
      source: "enterprise",
      sourceTable: "RealProductResearch + operations",
    };
  }

  const search = input.query?.trim();
  const conditions = [
    eq(knowledgeFile.workspaceId, input.workspaceId),
    sourceFileIds
      ? inArray(realProductResearch.sourceFileId, sourceFileIds)
      : undefined,
    input.category
      ? ilike(realProductResearch.category, textPattern(input.category))
      : undefined,
    input.logistics
      ? ilike(productOperation.logisticsTerm, textPattern(input.logistics))
      : undefined,
    input.operationStatus
      ? eq(
          productOperation.operationStatus,
          normalizeOperationStatusFilter(input.operationStatus)
        )
      : undefined,
    input.proposer
      ? ilike(productOperation.proposer, textPattern(input.proposer))
      : undefined,
    input.qualification
      ? ilike(productOperation.qualifications, textPattern(input.qualification))
      : undefined,
    input.targetChannel
      ? ilike(productOperation.targetChannels, textPattern(input.targetChannel))
      : undefined,
    search
      ? or(
          ilike(realProductResearch.productName, textPattern(search)),
          ilike(realProductResearch.category, textPattern(search)),
          ilike(realProductResearch.productHighlights, textPattern(search)),
          ilike(realProductResearch.productFeatures, textPattern(search)),
          ilike(realProductResearch.productIntro, textPattern(search)),
          ilike(realProductResearch.procurementConditions, textPattern(search)),
          ilike(realProductResearch.brand, textPattern(search))
        )
      : undefined,
  ].filter(Boolean);

  const rows = await db
    .select({
      operation: {
        logisticsTerm: productOperation.logisticsTerm,
        operationStatus: productOperation.operationStatus,
        promotionStatus: productOperation.promotionStatus,
        proposer: productOperation.proposer,
        qualifications: productOperation.qualifications,
      },
      research: {
        category: realProductResearch.category,
        contactPerson: realProductResearch.contactPerson,
        id: realProductResearch.id,
        procurementConditions: realProductResearch.procurementConditions,
        productFeatures: realProductResearch.productFeatures,
        productHighlights: realProductResearch.productHighlights,
        productIntro: realProductResearch.productIntro,
        productName: realProductResearch.productName,
        shippingTime: realProductResearch.shippingTime,
        sourceId: realProductResearch.sourceFileId,
        sourceRow: realProductResearch.sourceRow,
        sourceSheet: realProductResearch.sourceSheet,
        supplierContact: realProductResearch.supplierContact,
      },
      sourceFileName: knowledgeFile.originalName,
    })
    .from(realProductResearch)
    .leftJoin(
      productOperation,
      eq(productOperation.researchId, realProductResearch.id)
    )
    .leftJoin(
      knowledgeFile,
      eq(realProductResearch.sourceFileId, knowledgeFile.id)
    )
    .where(and(...conditions))
    .orderBy(asc(realProductResearch.productName));

  const researchIds = rows.map(({ research }) => research.id);
  const [priceRows, documentRows] =
    researchIds.length === 0
      ? [[], []]
      : await Promise.all([
          db
            .select({
              currency: productPrice.currency,
              priceMax: productPrice.priceMax,
              priceMin: productPrice.priceMin,
              priceType: productPrice.priceType,
              researchId: productPrice.researchId,
              variant: productPrice.variant,
            })
            .from(productPrice)
            .where(inArray(productPrice.researchId, researchIds)),
          db
            .select({ researchId: productDocument.researchId })
            .from(productDocument)
            .where(inArray(productDocument.researchId, researchIds)),
        ]);
  const pricesByResearchId = new Map<string, typeof priceRows>();
  for (const price of priceRows) {
    const existing = pricesByResearchId.get(price.researchId) ?? [];
    existing.push(price);
    pricesByResearchId.set(price.researchId, existing);
  }
  const documentCountByResearchId = new Map<string, number>();
  for (const document of documentRows) {
    documentCountByResearchId.set(
      document.researchId,
      (documentCountByResearchId.get(document.researchId) ?? 0) + 1
    );
  }

  const products = rows
    .map(({ research, operation, sourceFileName }) => {
      const prices = pricesByResearchId.get(research.id) ?? [];
      const usdPrices = prices
        .filter(({ currency }) => currency === "USD")
        .flatMap(({ priceMax, priceMin }) =>
          [priceMin, priceMax].filter(
            (price): price is string => price !== null
          )
        )
        .map(Number)
        .filter(Number.isFinite);
      const leadTimeDays = extractLeadDays(research.shippingTime);
      const documentCount = documentCountByResearchId.get(research.id) ?? 0;

      return {
        documentCount,
        leadTimeDays,
        operation,
        prices,
        research,
        sourceFileName,
        usdPrices,
      };
    })
    .filter(
      ({
        documentCount,
        operation,
        prices,
        leadTimeDays,
        research,
        usdPrices,
      }) => {
        if (
          input.maxPriceUsd !== undefined &&
          (usdPrices.length === 0 || Math.min(...usdPrices) > input.maxPriceUsd)
        ) {
          return false;
        }

        if (
          input.maxLeadDays !== undefined &&
          (leadTimeDays === null || leadTimeDays > input.maxLeadDays)
        ) {
          return false;
        }

        if (
          input.hasDocument !== undefined &&
          documentCount > 0 !== input.hasDocument
        ) {
          return false;
        }

        if (input.missingField === "price" && prices.length > 0) {
          return false;
        }
        if (
          input.missingField === "supplier" &&
          (research.supplierContact || research.contactPerson)
        ) {
          return false;
        }
        if (
          input.missingField === "qualification" &&
          operation?.qualifications
        ) {
          return false;
        }
        if (input.missingField === "document" && documentCount > 0) {
          return false;
        }
        if (
          input.missingField === "promotionStatus" &&
          operation?.promotionStatus
        ) {
          return false;
        }

        return true;
      }
    )
    .sort((a, b) => {
      const aPrice =
        a.usdPrices.length > 0
          ? Math.min(...a.usdPrices)
          : Number.POSITIVE_INFINITY;
      const bPrice =
        b.usdPrices.length > 0
          ? Math.min(...b.usdPrices)
          : Number.POSITIVE_INFINITY;
      return (
        aPrice - bPrice ||
        a.research.productName.localeCompare(b.research.productName)
      );
    })
    .slice(0, resultLimit(input.limit))
    .map(
      ({
        documentCount,
        operation,
        research,
        prices,
        leadTimeDays,
        sourceFileName,
      }) => ({
        category: research.category ?? "未分类",
        customization: research.procurementConditions,
        documentCount,
        hasDocuments: documentCount > 0,
        leadTimeDays,
        logisticsTerm: operation?.logisticsTerm ?? null,
        material: research.productFeatures,
        moqUnits: null,
        nameEn: research.productName,
        nameTr: null,
        nameZh: research.productName,
        operationStatus: operation?.operationStatus ?? null,
        priceCurrency: prices[0]?.currency ?? null,
        priceMax: prices[0]?.priceMax ?? null,
        priceMin: prices[0]?.priceMin ?? null,
        priceSummary:
          prices.length > 0
            ? prices
                .slice(0, 8)
                .map(
                  ({ currency, priceMax, priceMin, variant }) =>
                    `${variant}: ${currency} ${priceMin}${priceMax ? `-${priceMax}` : ""}`
                )
                .join("; ")
            : null,
        productId: `REAL-${research.sourceSheet}-${research.sourceRow}`,
        promotionStatus: operation?.promotionStatus ?? null,
        proposer: operation?.proposer ?? null,
        qualifications: operation?.qualifications ?? null,
        sampleAvailable: null,
        sku: null,
        sourceFileName,
        sourceId: research.sourceId,
        sourceRow: research.sourceRow,
        sourceSheet: research.sourceSheet,
        citation: {
          fileName: sourceFileName,
          row: research.sourceRow,
          sheet: research.sourceSheet,
          sourceId: research.sourceId,
        },
        supplierCity: null,
        supplierId: null,
        supplierName:
          research.contactPerson ?? research.supplierContact ?? "未提供",
        supplierQualityRating: null,
        unitPriceUsd:
          prices.find(({ currency }) => currency === "USD")?.priceMin ?? null,
      })
    );

  return {
    ...(missingSourceFileNames.length > 0
      ? {
          message: `Source files not found: ${missingSourceFileNames.join(", ")}`,
        }
      : {}),
    products,
    source: "enterprise",
    sourceTable: "RealProductResearch + operations",
  };
}

export async function searchProducts(
  input: SearchProductsInput,
  requestId?: string
) {
  if (isMockDatabase) {
    return {
      message: "Trade data is not loaded in mock mode.",
      products: [],
      source: "mock" as const,
    };
  }

  const startedAt = Date.now();
  logEvent("info", "db.search_products.start", { requestId });

  try {
    const result = await searchEnterpriseProducts(input);
    logEvent("info", "db.search_products.success", {
      durationMs: Date.now() - startedAt,
      requestId,
      resultCount: result.products.length,
    });
    return result;
  } catch (error) {
    logError("db.search_products.error", error, {
      durationMs: Date.now() - startedAt,
      requestId,
    });
    throw error;
  }
}
