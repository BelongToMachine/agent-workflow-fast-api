-- Employee members can query knowledge data, but cannot manage the knowledge base.
ALTER TABLE "WorkspaceMember"
  DROP CONSTRAINT IF EXISTS "WorkspaceMember_role_check";--> statement-breakpoint
ALTER TABLE "WorkspaceMember"
  ADD CONSTRAINT "WorkspaceMember_role_check"
  CHECK ("role" IN ('owner', 'admin', 'editor', 'employee', 'viewer'));
