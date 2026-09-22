CREATE TABLE "Supplier" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"supplierId" varchar(32) NOT NULL,
	"nameEn" text NOT NULL,
	"nameZh" text,
	"city" text,
	"province" text,
	"categoryTags" text,
	"contactLanguage" text,
	"typicalLeadDays" integer,
	"qualityRating" numeric(2, 1),
	"status" varchar(20) NOT NULL,
	CONSTRAINT "Supplier_supplierId_unique" UNIQUE("supplierId")
);
--> statement-breakpoint
CREATE TABLE "SellerRequest" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"requestId" varchar(32) NOT NULL,
	"sellerAlias" text NOT NULL,
	"market" text NOT NULL,
	"requestedAt" timestamp NOT NULL,
	"language" text,
	"category" text NOT NULL,
	"productKeywords" text,
	"quantityUnits" integer,
	"targetUnitPriceUsd" numeric(10, 2),
	"maxMoqUnits" integer,
	"maxLeadDays" integer,
	"customizationRequired" text,
	CONSTRAINT "SellerRequest_requestId_unique" UNIQUE("requestId")
);
--> statement-breakpoint
CREATE TABLE "Product" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"productId" varchar(32) NOT NULL,
	"supplierId" varchar(32) NOT NULL,
	"sku" text NOT NULL,
	"nameEn" text NOT NULL,
	"nameZh" text,
	"nameTr" text,
	"category" text NOT NULL,
	"material" text,
	"unitPriceUsd" numeric(10, 2),
	"moqUnits" integer,
	"leadTimeDays" integer,
	"customization" text,
	"sampleAvailable" boolean,
	"packageType" text,
	"weightKg" numeric(8, 2),
	CONSTRAINT "Product_productId_unique" UNIQUE("productId")
);
--> statement-breakpoint
CREATE TABLE "SupplierQuote" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"quoteId" varchar(32) NOT NULL,
	"requestId" varchar(32) NOT NULL,
	"supplierId" varchar(32) NOT NULL,
	"productId" varchar(32) NOT NULL,
	"quotedUnitPriceUsd" numeric(10, 2),
	"moqUnits" integer,
	"leadTimeDays" integer,
	"sampleFeeUsd" numeric(10, 2),
	"shippingEstimateUsd" numeric(10, 2),
	"quoteStatus" varchar(20) NOT NULL,
	"notes" text,
	CONSTRAINT "SupplierQuote_quoteId_unique" UNIQUE("quoteId")
);
--> statement-breakpoint
ALTER TABLE "Product" ADD CONSTRAINT "Product_supplierId_Supplier_supplierId_fk" FOREIGN KEY ("supplierId") REFERENCES "public"."Supplier"("supplierId") ON DELETE no action ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "SupplierQuote" ADD CONSTRAINT "SupplierQuote_requestId_SellerRequest_requestId_fk" FOREIGN KEY ("requestId") REFERENCES "public"."SellerRequest"("requestId") ON DELETE no action ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "SupplierQuote" ADD CONSTRAINT "SupplierQuote_supplierId_Supplier_supplierId_fk" FOREIGN KEY ("supplierId") REFERENCES "public"."Supplier"("supplierId") ON DELETE no action ON UPDATE no action;
--> statement-breakpoint
ALTER TABLE "SupplierQuote" ADD CONSTRAINT "SupplierQuote_productId_Product_productId_fk" FOREIGN KEY ("productId") REFERENCES "public"."Product"("productId") ON DELETE no action ON UPDATE no action;
