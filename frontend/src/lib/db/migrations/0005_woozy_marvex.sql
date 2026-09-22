CREATE TABLE "KnowledgeSource" (
	"createdAt" timestamp DEFAULT now() NOT NULL,
	"displayName" text NOT NULL,
	"fileHash" text,
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"sourceType" varchar(32) NOT NULL,
	"status" varchar(16) DEFAULT 'pending' NOT NULL,
	"storageKey" text,
	"storageProvider" varchar(16),
	"updatedAt" timestamp DEFAULT now() NOT NULL,
	"version" integer DEFAULT 1 NOT NULL
);
--> statement-breakpoint
DROP INDEX "ContentRecord_sourceSheet_sourceRow_idx";--> statement-breakpoint
DROP INDEX "RealProductResearch_sourceSheet_sourceRow_idx";--> statement-breakpoint
ALTER TABLE "ContentRecord" ADD COLUMN "sourceId" uuid;--> statement-breakpoint
ALTER TABLE "ProductDocument" ADD COLUMN "sourceId" uuid;--> statement-breakpoint
ALTER TABLE "RealProductResearch" ADD COLUMN "sourceId" uuid;--> statement-breakpoint
CREATE INDEX "KnowledgeSource_fileHash_idx" ON "KnowledgeSource" USING btree ("fileHash");--> statement-breakpoint
ALTER TABLE "ContentRecord" ADD CONSTRAINT "ContentRecord_sourceId_KnowledgeSource_id_fk" FOREIGN KEY ("sourceId") REFERENCES "public"."KnowledgeSource"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ProductDocument" ADD CONSTRAINT "ProductDocument_sourceId_KnowledgeSource_id_fk" FOREIGN KEY ("sourceId") REFERENCES "public"."KnowledgeSource"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "RealProductResearch" ADD CONSTRAINT "RealProductResearch_sourceId_KnowledgeSource_id_fk" FOREIGN KEY ("sourceId") REFERENCES "public"."KnowledgeSource"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "ContentRecord_sourceId_idx" ON "ContentRecord" USING btree ("sourceId");--> statement-breakpoint
CREATE UNIQUE INDEX "ContentRecord_sourceId_sourceSheet_sourceRow_idx" ON "ContentRecord" USING btree ("sourceId","sourceSheet","sourceRow");--> statement-breakpoint
CREATE INDEX "ProductDocument_sourceId_idx" ON "ProductDocument" USING btree ("sourceId");--> statement-breakpoint
CREATE INDEX "RealProductResearch_sourceId_idx" ON "RealProductResearch" USING btree ("sourceId");--> statement-breakpoint
CREATE UNIQUE INDEX "RealProductResearch_sourceId_sourceSheet_sourceRow_idx" ON "RealProductResearch" USING btree ("sourceId","sourceSheet","sourceRow");