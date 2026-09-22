CREATE TABLE "AuditLog" (
	"action" varchar(64) NOT NULL,
	"actorUserId" uuid,
	"createdAt" timestamp DEFAULT now() NOT NULL,
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"targetUserId" uuid,
	"workspaceId" uuid NOT NULL
);
--> statement-breakpoint
CREATE TABLE "Workspace" (
	"createdAt" timestamp DEFAULT now() NOT NULL,
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"ownerId" uuid,
	"updatedAt" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "WorkspaceMember" (
	"createdAt" timestamp DEFAULT now() NOT NULL,
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"role" varchar(16) DEFAULT 'viewer' NOT NULL,
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"updatedAt" timestamp DEFAULT now() NOT NULL,
	"userId" uuid NOT NULL,
	"workspaceId" uuid NOT NULL
);
--> statement-breakpoint
CREATE TABLE "WorkspaceMemberPermission" (
	"effect" varchar(8) NOT NULL,
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"memberId" uuid NOT NULL,
	"permission" varchar(64) NOT NULL,
	"updatedAt" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
INSERT INTO "Workspace" ("id", "name")
VALUES ('00000000-0000-0000-0000-000000000001', 'Asianode Default Workspace')
ON CONFLICT ("id") DO NOTHING;--> statement-breakpoint
WITH ranked_users AS (
  SELECT
    "id",
    "email",
    "isAnonymous",
    row_number() OVER (
      ORDER BY CASE WHEN "email" LIKE 'guest-%' THEN 1 ELSE 0 END, "createdAt", "id"
    ) AS "rowNumber"
  FROM "User"
)
INSERT INTO "WorkspaceMember" ("role", "status", "userId", "workspaceId")
SELECT
  CASE
    WHEN "rowNumber" = 1 THEN 'owner'
    WHEN "isAnonymous" OR "email" LIKE 'guest-%' THEN 'viewer'
    ELSE 'editor'
  END,
  'active',
  "id",
  '00000000-0000-0000-0000-000000000001'
FROM ranked_users
ON CONFLICT DO NOTHING;--> statement-breakpoint
UPDATE "Workspace"
SET "ownerId" = (
  SELECT "id"
  FROM "User"
  ORDER BY CASE WHEN "email" LIKE 'guest-%' THEN 1 ELSE 0 END, "createdAt", "id"
  LIMIT 1
)
WHERE "id" = '00000000-0000-0000-0000-000000000001';--> statement-breakpoint
ALTER TABLE "Chat" ADD COLUMN "workspaceId" uuid;--> statement-breakpoint
ALTER TABLE "Document" ADD COLUMN "workspaceId" uuid;--> statement-breakpoint
ALTER TABLE "KnowledgeSource" ADD COLUMN "workspaceId" uuid;--> statement-breakpoint
UPDATE "Chat"
SET "workspaceId" = '00000000-0000-0000-0000-000000000001'
WHERE "workspaceId" IS NULL;--> statement-breakpoint
UPDATE "Document"
SET "workspaceId" = '00000000-0000-0000-0000-000000000001'
WHERE "workspaceId" IS NULL;--> statement-breakpoint
UPDATE "KnowledgeSource"
SET "workspaceId" = '00000000-0000-0000-0000-000000000001'
WHERE "workspaceId" IS NULL;--> statement-breakpoint
ALTER TABLE "Chat" ALTER COLUMN "workspaceId" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "Document" ALTER COLUMN "workspaceId" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "KnowledgeSource" ALTER COLUMN "workspaceId" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_actorUserId_User_id_fk" FOREIGN KEY ("actorUserId") REFERENCES "public"."User"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_targetUserId_User_id_fk" FOREIGN KEY ("targetUserId") REFERENCES "public"."User"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_workspaceId_Workspace_id_fk" FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "Workspace" ADD CONSTRAINT "Workspace_ownerId_User_id_fk" FOREIGN KEY ("ownerId") REFERENCES "public"."User"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "WorkspaceMember" ADD CONSTRAINT "WorkspaceMember_userId_User_id_fk" FOREIGN KEY ("userId") REFERENCES "public"."User"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "WorkspaceMember" ADD CONSTRAINT "WorkspaceMember_workspaceId_Workspace_id_fk" FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "WorkspaceMemberPermission" ADD CONSTRAINT "WorkspaceMemberPermission_memberId_WorkspaceMember_id_fk" FOREIGN KEY ("memberId") REFERENCES "public"."WorkspaceMember"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "AuditLog_workspace_created_idx" ON "AuditLog" USING btree ("workspaceId","createdAt");--> statement-breakpoint
CREATE UNIQUE INDEX "WorkspaceMember_workspace_user_idx" ON "WorkspaceMember" USING btree ("workspaceId","userId");--> statement-breakpoint
CREATE INDEX "WorkspaceMember_workspace_idx" ON "WorkspaceMember" USING btree ("workspaceId");--> statement-breakpoint
CREATE UNIQUE INDEX "WorkspaceMemberPermission_member_permission_idx" ON "WorkspaceMemberPermission" USING btree ("memberId","permission");--> statement-breakpoint
ALTER TABLE "Chat" ADD CONSTRAINT "Chat_workspaceId_Workspace_id_fk" FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "Document" ADD CONSTRAINT "Document_workspaceId_Workspace_id_fk" FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "KnowledgeSource" ADD CONSTRAINT "KnowledgeSource_workspaceId_Workspace_id_fk" FOREIGN KEY ("workspaceId") REFERENCES "public"."Workspace"("id") ON DELETE no action ON UPDATE no action;
