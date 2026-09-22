UPDATE "User"
SET "isAnonymous" = true
WHERE "email" LIKE 'guest-%';--> statement-breakpoint
UPDATE "WorkspaceMember"
SET "role" = 'viewer',
"updatedAt" = now()
WHERE "workspaceId" = '00000000-0000-0000-0000-000000000001'
  AND "userId" IN (
    SELECT "id"
    FROM "User"
    WHERE "email" LIKE 'guest-%'
  );
