CREATE TABLE "ProductDocument" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"researchId" uuid NOT NULL,
	"sourceSheet" varchar(64) NOT NULL,
	"sourceRow" integer NOT NULL,
	"documentType" varchar(24) NOT NULL,
	"fileReference" text NOT NULL,
	"displayName" text,
	"rawText" text NOT NULL,
	"createdAt" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ProductOperation" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"researchId" uuid NOT NULL,
	"sourceSheet" varchar(64) NOT NULL,
	"sourceRow" integer NOT NULL,
	"promotionStatus" text,
	"operationStatus" varchar(32) DEFAULT 'unknown' NOT NULL,
	"targetChannels" text,
	"proposer" text,
	"logisticsTerm" varchar(16),
	"qualifications" text,
	"nextAction" text,
	"notes" text,
	"rawData" jsonb NOT NULL,
	"updatedAt" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ProductPrice" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"researchId" uuid NOT NULL,
	"sourceSheet" varchar(64) NOT NULL,
	"sourceRow" integer NOT NULL,
	"variant" text NOT NULL,
	"priceMin" numeric(12, 2) NOT NULL,
	"priceMax" numeric(12, 2),
	"currency" varchar(8) NOT NULL,
	"priceType" varchar(24) NOT NULL,
	"rawText" text NOT NULL
);
--> statement-breakpoint
ALTER TABLE "ProductDocument" ADD CONSTRAINT "ProductDocument_researchId_RealProductResearch_id_fk" FOREIGN KEY ("researchId") REFERENCES "public"."RealProductResearch"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ProductOperation" ADD CONSTRAINT "ProductOperation_researchId_RealProductResearch_id_fk" FOREIGN KEY ("researchId") REFERENCES "public"."RealProductResearch"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ProductPrice" ADD CONSTRAINT "ProductPrice_researchId_RealProductResearch_id_fk" FOREIGN KEY ("researchId") REFERENCES "public"."RealProductResearch"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "ProductDocument_reference_idx" ON "ProductDocument" USING btree ("researchId","documentType","fileReference");--> statement-breakpoint
CREATE UNIQUE INDEX "ProductOperation_researchId_idx" ON "ProductOperation" USING btree ("researchId");--> statement-breakpoint
CREATE UNIQUE INDEX "ProductPrice_source_idx" ON "ProductPrice" USING btree ("researchId","variant","priceMin","currency","priceType");