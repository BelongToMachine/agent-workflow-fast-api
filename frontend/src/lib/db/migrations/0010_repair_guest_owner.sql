WITH owner_candidate AS (
  SELECT "id"
  FROM "User"
  WHERE "isAnonymous" = false
    AND "email" NOT LIKE 'guest-%'
  ORDER BY "createdAt", "id"
  LIMIT 1
)
UPDATE "Workspace"
SET "ownerId" = (SELECT "id" FROM owner_candidate)
WHERE "id" = '00000000-0000-0000-0000-000000000001'
  AND EXISTS (SELECT 1 FROM owner_candidate);--> statement-breakpoint
WITH owner_candidate AS (
  SELECT "id"
  FROM "User"
  WHERE "isAnonymous" = false
    AND "email" NOT LIKE 'guest-%'
  ORDER BY "createdAt", "id"
  LIMIT 1
)
UPDATE "WorkspaceMember"
SET "role" = CASE
  WHEN "userId" = (SELECT "id" FROM owner_candidate) THEN 'owner'
  ELSE 'editor'
END,
"updatedAt" = now()
WHERE "workspaceId" = '00000000-0000-0000-0000-000000000001'
  AND EXISTS (SELECT 1 FROM owner_candidate);
