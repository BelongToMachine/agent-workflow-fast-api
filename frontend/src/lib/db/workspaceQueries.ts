import "server-only";

import { and, asc, count, eq, inArray } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import {
  defaultPermissionsByRole,
  getEffectivePermissions,
  type Permission,
  type WorkspaceRole,
  workspaceRoles,
} from "@/lib/permissions";
import { DEFAULT_WORKSPACE_ID, isMockDatabase } from "../constants";
import {
  auditLog,
  user,
  workspace,
  workspaceMember,
  workspaceMemberPermission,
} from "./schema";

const db = isMockDatabase
  ? (undefined as never)
  : drizzle(postgres(process.env.POSTGRES_URL ?? ""));

export type PermissionOverride = {
  effect: "grant" | "deny";
  permission: string;
};

export type WorkspaceMembership = {
  id: string;
  role: WorkspaceRole;
  status: "active" | "suspended";
  userId: string;
  workspaceId: string;
  workspaceName: string;
  overrides: PermissionOverride[];
};

export type WorkspaceMemberView = WorkspaceMembership & {
  email: string;
  effectivePermissions: Permission[];
  name: string | null;
};

function assertRole(role: string): WorkspaceRole {
  if (!workspaceRoles.includes(role as WorkspaceRole)) {
    throw new Error(`Unsupported workspace role: ${role}`);
  }

  return role as WorkspaceRole;
}

function getPermissionOverrides(memberId: string) {
  return db
    .select({
      effect: workspaceMemberPermission.effect,
      permission: workspaceMemberPermission.permission,
    })
    .from(workspaceMemberPermission)
    .where(eq(workspaceMemberPermission.memberId, memberId));
}

export async function getWorkspaceMembershipForUser(userId: string) {
  if (isMockDatabase) {
    return {
      id: "mock-membership",
      overrides: [],
      role: "owner" as const,
      status: "active" as const,
      userId,
      workspaceId: DEFAULT_WORKSPACE_ID,
      workspaceName: "Asianode Default Workspace",
    };
  }

  const [row] = await db
    .select({
      id: workspaceMember.id,
      role: workspaceMember.role,
      status: workspaceMember.status,
      userId: workspaceMember.userId,
      workspaceId: workspaceMember.workspaceId,
      workspaceName: workspace.name,
    })
    .from(workspaceMember)
    .innerJoin(workspace, eq(workspaceMember.workspaceId, workspace.id))
    .where(
      and(
        eq(workspaceMember.userId, userId),
        eq(workspaceMember.status, "active")
      )
    )
    .orderBy(asc(workspaceMember.createdAt))
    .limit(1);

  if (!row) {
    return null;
  }

  return {
    ...row,
    overrides: await getPermissionOverrides(row.id),
  } as WorkspaceMembership;
}

export async function ensureDefaultWorkspaceMembership(
  userId: string,
  role: WorkspaceRole = "viewer"
) {
  if (isMockDatabase) {
    return null;
  }

  const [membership] = await db
    .insert(workspaceMember)
    .values({
      role,
      userId,
      workspaceId: DEFAULT_WORKSPACE_ID,
    })
    .onConflictDoNothing({
      target: [workspaceMember.workspaceId, workspaceMember.userId],
    })
    .returning();

  return membership ?? null;
}

export async function listWorkspaceMembers(workspaceId: string) {
  if (isMockDatabase) {
    return [];
  }

  const members = await db
    .select({
      email: user.email,
      id: workspaceMember.id,
      name: user.name,
      role: workspaceMember.role,
      status: workspaceMember.status,
      userId: workspaceMember.userId,
      workspaceId: workspaceMember.workspaceId,
      workspaceName: workspace.name,
    })
    .from(workspaceMember)
    .innerJoin(user, eq(workspaceMember.userId, user.id))
    .innerJoin(workspace, eq(workspaceMember.workspaceId, workspace.id))
    .where(eq(workspaceMember.workspaceId, workspaceId))
    .orderBy(asc(workspaceMember.createdAt));

  const memberIds = members.map(({ id }) => id);
  const overrides =
    memberIds.length === 0
      ? []
      : await db
          .select({
            effect: workspaceMemberPermission.effect,
            memberId: workspaceMemberPermission.memberId,
            permission: workspaceMemberPermission.permission,
          })
          .from(workspaceMemberPermission)
          .where(inArray(workspaceMemberPermission.memberId, memberIds));

  return members.map((member) => {
    const memberOverrides = overrides
      .filter(({ memberId }) => memberId === member.id)
      .map(({ effect, permission }) => ({ effect, permission }));
    const effectivePermissions = [
      ...getEffectivePermissions(assertRole(member.role), memberOverrides),
    ];

    return {
      ...member,
      effectivePermissions,
      overrides: memberOverrides,
    } as WorkspaceMemberView;
  });
}

export async function updateWorkspaceMemberAccess({
  actorUserId,
  memberId,
  permissions,
  role,
  workspaceId,
}: {
  actorUserId: string;
  memberId: string;
  permissions: Permission[];
  role: WorkspaceRole;
  workspaceId: string;
}) {
  if (isMockDatabase) {
    throw new Error("Permission management requires a PostgreSQL database.");
  }

  const result = await db.transaction(async (tx) => {
    const [actor] = await tx
      .select({ role: workspaceMember.role })
      .from(workspaceMember)
      .where(
        and(
          eq(workspaceMember.userId, actorUserId),
          eq(workspaceMember.workspaceId, workspaceId),
          eq(workspaceMember.status, "active")
        )
      )
      .limit(1);

    const [target] = await tx
      .select({
        role: workspaceMember.role,
        userId: workspaceMember.userId,
      })
      .from(workspaceMember)
      .where(
        and(
          eq(workspaceMember.id, memberId),
          eq(workspaceMember.workspaceId, workspaceId)
        )
      )
      .limit(1);

    if (!actor || !target) {
      throw new Error("Workspace member not found.");
    }

    const actorRole = assertRole(actor.role);
    const targetRole = assertRole(target.role);

    if (targetRole === "owner" && actorRole !== "owner") {
      throw new Error("Only the workspace owner can edit an owner.");
    }

    if (role === "owner" && actorRole !== "owner") {
      throw new Error("Only the workspace owner can grant owner access.");
    }

    if (target.userId === actorUserId) {
      const resultingPermissions = new Set(permissions);
      if (
        !resultingPermissions.has("members.manage") ||
        !["owner", "admin"].includes(role)
      ) {
        throw new Error("You cannot remove your own member-management access.");
      }
    }

    if (targetRole === "owner" && role !== "owner") {
      const [{ ownerCount }] = await tx
        .select({ ownerCount: count() })
        .from(workspaceMember)
        .where(
          and(
            eq(workspaceMember.workspaceId, workspaceId),
            eq(workspaceMember.role, "owner"),
            eq(workspaceMember.status, "active")
          )
        );

      if (Number(ownerCount) <= 1) {
        throw new Error("The workspace must keep at least one owner.");
      }
    }

    await tx
      .update(workspaceMember)
      .set({ role, updatedAt: new Date() })
      .where(eq(workspaceMember.id, memberId));

    await tx
      .delete(workspaceMemberPermission)
      .where(eq(workspaceMemberPermission.memberId, memberId));

    const defaultPermissions = new Set(defaultPermissionsByRole[role]);
    const customPermissions = permissions
      .filter((permission) => !defaultPermissions.has(permission))
      .map((permission) => ({ effect: "grant" as const, permission }));
    const deniedPermissions = [...defaultPermissions]
      .filter((permission) => !permissions.includes(permission))
      .map((permission) => ({ effect: "deny" as const, permission }));
    const overrides = [...customPermissions, ...deniedPermissions];

    if (overrides.length > 0) {
      await tx.insert(workspaceMemberPermission).values(
        overrides.map(({ effect, permission }) => ({
          effect,
          memberId,
          permission,
          updatedAt: new Date(),
        }))
      );
    }

    await tx.insert(auditLog).values({
      action: "workspace.member_permissions_updated",
      actorUserId,
      metadata: {
        permissions,
        role,
      },
      targetUserId: target.userId,
      workspaceId,
    });

    return target.userId;
  });

  return {
    member: (await listWorkspaceMembers(workspaceId)).find(
      ({ userId }) => userId === result
    ),
  };
}
