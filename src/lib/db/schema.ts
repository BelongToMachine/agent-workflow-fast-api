import type { InferSelectModel } from "drizzle-orm";
import {
  boolean,
  foreignKey,
  index,
  integer,
  json,
  jsonb,
  numeric,
  pgTable,
  primaryKey,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";

export const user = pgTable("User", {
  createdAt: timestamp("createdAt").notNull().defaultNow(),
  email: varchar("email", { length: 64 }).notNull(),
  emailVerified: boolean("emailVerified").notNull().default(false),
  id: uuid("id").primaryKey().notNull().defaultRandom(),
  image: text("image"),
  isAnonymous: boolean("isAnonymous").notNull().default(false),
  name: text("name"),
  password: varchar("password", { length: 64 }),
  updatedAt: timestamp("updatedAt").notNull().defaultNow(),
});

export type User = InferSelectModel<typeof user>;

export const workspace = pgTable("Workspace", {
  createdAt: timestamp("createdAt").notNull().defaultNow(),
  id: uuid("id").primaryKey().notNull().defaultRandom(),
  name: text("name").notNull(),
  ownerId: uuid("ownerId").references(() => user.id),
  updatedAt: timestamp("updatedAt").notNull().defaultNow(),
});

export type Workspace = InferSelectModel<typeof workspace>;

export const workspaceMember = pgTable(
  "WorkspaceMember",
  {
    createdAt: timestamp("createdAt").notNull().defaultNow(),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    role: varchar("role", {
      enum: ["owner", "admin", "editor", "employee", "viewer"],
      length: 16,
    })
      .notNull()
      .default("viewer"),
    status: varchar("status", { enum: ["active", "suspended"], length: 16 })
      .notNull()
      .default("active"),
    updatedAt: timestamp("updatedAt").notNull().defaultNow(),
    userId: uuid("userId")
      .notNull()
      .references(() => user.id, { onDelete: "cascade" }),
    workspaceId: uuid("workspaceId")
      .notNull()
      .references(() => workspace.id, { onDelete: "cascade" }),
  },
  (table) => ({
    workspaceIdx: index("WorkspaceMember_workspace_idx").on(table.workspaceId),
    workspaceUserUnique: uniqueIndex("WorkspaceMember_workspace_user_idx").on(
      table.workspaceId,
      table.userId
    ),
  })
);

export type WorkspaceMember = InferSelectModel<typeof workspaceMember>;

export const workspaceMemberPermission = pgTable(
  "WorkspaceMemberPermission",
  {
    effect: varchar("effect", { enum: ["grant", "deny"], length: 8 }).notNull(),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    memberId: uuid("memberId")
      .notNull()
      .references(() => workspaceMember.id, { onDelete: "cascade" }),
    permission: varchar("permission", { length: 64 }).notNull(),
    updatedAt: timestamp("updatedAt").notNull().defaultNow(),
  },
  (table) => ({
    memberPermissionUnique: uniqueIndex(
      "WorkspaceMemberPermission_member_permission_idx"
    ).on(table.memberId, table.permission),
  })
);

export type WorkspaceMemberPermission = InferSelectModel<
  typeof workspaceMemberPermission
>;

export const auditLog = pgTable(
  "AuditLog",
  {
    action: varchar("action", { length: 64 }).notNull(),
    actorUserId: uuid("actorUserId").references(() => user.id),
    createdAt: timestamp("createdAt").notNull().defaultNow(),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    metadata: jsonb("metadata").notNull().default({}),
    targetUserId: uuid("targetUserId").references(() => user.id),
    workspaceId: uuid("workspaceId")
      .notNull()
      .references(() => workspace.id, { onDelete: "cascade" }),
  },
  (table) => ({
    workspaceCreatedIdx: index("AuditLog_workspace_created_idx").on(
      table.workspaceId,
      table.createdAt
    ),
  })
);

export type AuditLog = InferSelectModel<typeof auditLog>;

export const chat = pgTable("Chat", {
  createdAt: timestamp("createdAt").notNull(),
  id: uuid("id").primaryKey().notNull().defaultRandom(),
  title: text("title").notNull(),
  userId: uuid("userId")
    .notNull()
    .references(() => user.id),
  visibility: varchar("visibility", { enum: ["public", "private"] })
    .notNull()
    .default("private"),
  workspaceId: uuid("workspaceId")
    .notNull()
    .references(() => workspace.id),
});

export type Chat = InferSelectModel<typeof chat>;

export const message = pgTable("Message_v2", {
  attachments: json("attachments").notNull(),
  chatId: uuid("chatId")
    .notNull()
    .references(() => chat.id),
  createdAt: timestamp("createdAt").notNull(),
  id: uuid("id").primaryKey().notNull().defaultRandom(),
  parts: json("parts").notNull(),
  role: varchar("role").notNull(),
});

export type DBMessage = InferSelectModel<typeof message>;

export const document = pgTable(
  "Document",
  {
    content: text("content"),
    createdAt: timestamp("createdAt").notNull(),
    id: uuid("id").notNull().defaultRandom(),
    kind: varchar("text", { enum: ["text", "code", "image", "sheet"] })
      .notNull()
      .default("text"),
    title: text("title").notNull(),
    userId: uuid("userId")
      .notNull()
      .references(() => user.id),
    workspaceId: uuid("workspaceId")
      .notNull()
      .references(() => workspace.id),
  },
  (table) => ({
    pk: primaryKey({ columns: [table.id, table.createdAt] }),
  })
);

export type Document = InferSelectModel<typeof document>;

export const suggestion = pgTable(
  "Suggestion",
  {
    createdAt: timestamp("createdAt").notNull(),
    description: text("description"),
    documentCreatedAt: timestamp("documentCreatedAt").notNull(),
    documentId: uuid("documentId").notNull(),
    id: uuid("id").notNull().defaultRandom(),
    isResolved: boolean("isResolved").notNull().default(false),
    originalText: text("originalText").notNull(),
    suggestedText: text("suggestedText").notNull(),
    userId: uuid("userId")
      .notNull()
      .references(() => user.id),
  },
  (table) => ({
    documentRef: foreignKey({
      columns: [table.documentId, table.documentCreatedAt],
      foreignColumns: [document.id, document.createdAt],
    }),
    pk: primaryKey({ columns: [table.id] }),
  })
);

export type Suggestion = InferSelectModel<typeof suggestion>;

export const stream = pgTable(
  "Stream",
  {
    chatId: uuid("chatId").notNull(),
    createdAt: timestamp("createdAt").notNull(),
    id: uuid("id").notNull().defaultRandom(),
  },
  (table) => ({
    chatRef: foreignKey({
      columns: [table.chatId],
      foreignColumns: [chat.id],
    }),
    pk: primaryKey({ columns: [table.id] }),
  })
);

export type Stream = InferSelectModel<typeof stream>;

export const knowledgeSource = pgTable(
  "KnowledgeSource",
  {
    createdAt: timestamp("createdAt").notNull().defaultNow(),
    displayName: text("displayName").notNull(),
    fileHash: text("fileHash"),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    sourceType: varchar("sourceType", { length: 32 }).notNull(),
    status: varchar("status", { length: 16 }).notNull().default("pending"),
    storageKey: text("storageKey"),
    storageProvider: varchar("storageProvider", { length: 16 }),
    updatedAt: timestamp("updatedAt").notNull().defaultNow(),
    version: integer("version").notNull().default(1),
    workspaceId: uuid("workspaceId")
      .notNull()
      .references(() => workspace.id),
  },
  (table) => ({
    fileHashIdx: index("KnowledgeSource_fileHash_idx").on(table.fileHash),
  })
);

export type KnowledgeSource = InferSelectModel<typeof knowledgeSource>;

export const realProductResearch = pgTable(
  "RealProductResearch",
  {
    brand: text("brand"),
    category: text("category"),
    contactPerson: text("contactPerson"),
    costPrice: text("costPrice"),
    customsFee: text("customsFee"),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    listedPrice: text("listedPrice"),
    logistics: text("logistics"),
    notes: text("notes"),
    orderTotalPrice: text("orderTotalPrice"),
    procurementConditions: text("procurementConditions"),
    productFeatures: text("productFeatures"),
    productHighlights: text("productHighlights"),
    productImage: text("productImage"),
    productIntro: text("productIntro"),
    productName: text("productName").notNull(),
    promotionStatus: text("promotionStatus"),
    proposer: text("proposer"),
    qualifications: text("qualifications"),
    rawData: jsonb("rawData").notNull(),
    relatedDocuments: text("relatedDocuments"),
    sellingPrice: text("sellingPrice"),
    shippingTime: text("shippingTime"),
    singleProductCost: text("singleProductCost"),
    sourceId: uuid("sourceId")
      .notNull()
      .references(() => knowledgeSource.id),
    sourceRow: integer("sourceRow").notNull(),
    sourceSheet: varchar("sourceSheet", { length: 64 }).notNull(),
    supplierContact: text("supplierContact"),
    targetSalesChannels: text("targetSalesChannels"),
  },
  (table) => ({
    sourceIdIdx: index("RealProductResearch_sourceId_idx").on(table.sourceId),
    sourceRowUnique: uniqueIndex(
      "RealProductResearch_sourceId_sourceSheet_sourceRow_idx"
    ).on(table.sourceId, table.sourceSheet, table.sourceRow),
  })
);

export type RealProductResearch = InferSelectModel<typeof realProductResearch>;

export const productOperation = pgTable(
  "ProductOperation",
  {
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    logisticsTerm: varchar("logisticsTerm", { length: 16 }),
    nextAction: text("nextAction"),
    notes: text("notes"),
    operationStatus: varchar("operationStatus", { length: 32 })
      .notNull()
      .default("unknown"),
    promotionStatus: text("promotionStatus"),
    proposer: text("proposer"),
    qualifications: text("qualifications"),
    rawData: jsonb("rawData").notNull(),
    researchId: uuid("researchId")
      .notNull()
      .references(() => realProductResearch.id, { onDelete: "cascade" }),
    sourceRow: integer("sourceRow").notNull(),
    sourceSheet: varchar("sourceSheet", { length: 64 }).notNull(),
    targetChannels: text("targetChannels"),
    updatedAt: timestamp("updatedAt").notNull().defaultNow(),
  },
  (table) => ({
    researchUnique: uniqueIndex("ProductOperation_researchId_idx").on(
      table.researchId
    ),
  })
);

export type ProductOperation = InferSelectModel<typeof productOperation>;

export const productPrice = pgTable(
  "ProductPrice",
  {
    currency: varchar("currency", { length: 8 }).notNull(),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    priceMax: numeric("priceMax", { precision: 12, scale: 2 }),
    priceMin: numeric("priceMin", { precision: 12, scale: 2 }).notNull(),
    priceType: varchar("priceType", { length: 24 }).notNull(),
    rawText: text("rawText").notNull(),
    researchId: uuid("researchId")
      .notNull()
      .references(() => realProductResearch.id, { onDelete: "cascade" }),
    sourceRow: integer("sourceRow").notNull(),
    sourceSheet: varchar("sourceSheet", { length: 64 }).notNull(),
    variant: text("variant").notNull(),
  },
  (table) => ({
    sourceUnique: uniqueIndex("ProductPrice_source_idx").on(
      table.researchId,
      table.variant,
      table.priceMin,
      table.currency,
      table.priceType
    ),
  })
);

export type ProductPrice = InferSelectModel<typeof productPrice>;

export const productDocument = pgTable(
  "ProductDocument",
  {
    createdAt: timestamp("createdAt").notNull().defaultNow(),
    displayName: text("displayName"),
    documentType: varchar("documentType", { length: 24 }).notNull(),
    fileReference: text("fileReference").notNull(),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    rawText: text("rawText").notNull(),
    researchId: uuid("researchId")
      .notNull()
      .references(() => realProductResearch.id, { onDelete: "cascade" }),
    sourceId: uuid("sourceId")
      .notNull()
      .references(() => knowledgeSource.id),
    sourceRow: integer("sourceRow").notNull(),
    sourceSheet: varchar("sourceSheet", { length: 64 }).notNull(),
  },
  (table) => ({
    referenceUnique: uniqueIndex("ProductDocument_reference_idx").on(
      table.researchId,
      table.documentType,
      table.fileReference
    ),
    sourceIdIdx: index("ProductDocument_sourceId_idx").on(table.sourceId),
  })
);

export type ProductDocument = InferSelectModel<typeof productDocument>;

export const contentRecord = pgTable(
  "ContentRecord",
  {
    accountDirection: text("accountDirection"),
    accountName: text("accountName"),
    accountType: text("accountType"),
    aiMaterials: text("aiMaterials"),
    attachment: text("attachment"),
    copyText: text("copyText"),
    copyWriter: text("copyWriter"),
    createdAt: timestamp("createdAt").notNull().defaultNow(),
    id: uuid("id").primaryKey().notNull().defaultRandom(),
    language: text("language"),
    notes: text("notes"),
    photographer: text("photographer"),
    plannedAt: timestamp("plannedAt"),
    platform: text("platform"),
    product: text("product"),
    rawData: jsonb("rawData").notNull(),
    recordType: varchar("recordType", { length: 32 }).notNull(),
    referenceVideo: text("referenceVideo"),
    reviewStatus: text("reviewStatus"),
    revisedCopy: text("revisedCopy"),
    scriptDocument: text("scriptDocument"),
    searchText: text("searchText").notNull(),
    shootConfirmed: text("shootConfirmed"),
    shootingScene: text("shootingScene"),
    sourceId: uuid("sourceId")
      .notNull()
      .references(() => knowledgeSource.id),
    sourceRow: integer("sourceRow").notNull(),
    sourceSheet: varchar("sourceSheet", { length: 64 }).notNull(),
    submitter: text("submitter"),
    tags: text("tags"),
    targetTopic: text("targetTopic"),
    title: text("title"),
    usageStatus: text("usageStatus"),
    videoType: text("videoType"),
  },
  (table) => ({
    sourceIdIdx: index("ContentRecord_sourceId_idx").on(table.sourceId),
    sourceRowUnique: uniqueIndex(
      "ContentRecord_sourceId_sourceSheet_sourceRow_idx"
    ).on(table.sourceId, table.sourceSheet, table.sourceRow),
  })
);

export type ContentRecord = InferSelectModel<typeof contentRecord>;
