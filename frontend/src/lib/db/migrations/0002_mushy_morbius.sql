CREATE TABLE "RealProductResearch" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"sourceSheet" varchar(64) NOT NULL,
	"sourceRow" integer NOT NULL,
	"category" text,
	"productName" text NOT NULL,
	"productImage" text,
	"supplierContact" text,
	"contactPerson" text,
	"productHighlights" text,
	"productFeatures" text,
	"productIntro" text,
	"procurementConditions" text,
	"costPrice" text,
	"customsFee" text,
	"sellingPrice" text,
	"targetSalesChannels" text,
	"proposer" text,
	"promotionStatus" text,
	"logistics" text,
	"qualifications" text,
	"notes" text,
	"brand" text,
	"shippingTime" text,
	"listedPrice" text,
	"singleProductCost" text,
	"orderTotalPrice" text,
	"relatedDocuments" text,
	"rawData" jsonb NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "RealProductResearch_sourceSheet_sourceRow_idx" ON "RealProductResearch" USING btree ("sourceSheet","sourceRow");
--> statement-breakpoint
