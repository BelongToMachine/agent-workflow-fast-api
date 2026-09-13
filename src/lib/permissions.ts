export const workspaceRoles = ["owner", "admin", "editor", "employee", "viewer"] as const;

export type WorkspaceRole = (typeof workspaceRoles)[number];

export const permissionCatalog = [
  {
    description: "See workspace members and their current access.",
    key: "members.read",
    label: "View members",
  },
  {
    description: "Change roles and individual permissions.",
    key: "members.manage",
    label: "Manage members",
  },
  {
    description: "Use supplier, product, and content data in AI answers.",
    key: "knowledge.read",
    label: "Query knowledge base",
  },
  {
    description: "Import, update, archive, or delete source data.",
    key: "knowledge.manage",
    label: "Manage knowledge base",
  },
  {
    description: "Open workspace chat history and responses.",
    key: "chat.read",
    label: "View chats",
  },
  {
    description: "Send messages and run AI requests.",
    key: "chat.write",
    label: "Create chats",
  },
  {
    description: "Remove chat history owned by the member.",
    key: "chat.delete",
    label: "Delete chats",
  },
  {
    description: "Open generated artifacts and document versions.",
    key: "document.read",
    label: "View documents",
  },
  {
    description: "Create, edit, and upload document content.",
    key: "document.write",
    label: "Edit documents",
  },
  {
    description: "Review permission and workspace security events.",
    key: "audit.read",
    label: "View audit log",
  },
] as const;

export type Permission = (typeof permissionCatalog)[number]["key"];

const allPermissions = permissionCatalog.map(({ key }) => key) as Permission[];

export const defaultPermissionsByRole: Record<WorkspaceRole, Permission[]> = {
  admin: allPermissions,
  editor: [
    "knowledge.read",
    "knowledge.manage",
    "chat.read",
    "chat.write",
    "chat.delete",
    "document.read",
    "document.write",
  ],
  employee: [
    "knowledge.read",
    "chat.read",
    "chat.write",
    "chat.delete",
    "document.read",
    "document.write",
  ],
  owner: allPermissions,
  viewer: ["knowledge.read", "chat.read", "chat.write", "document.read"],
};

export const roleLabels: Record<WorkspaceRole, string> = {
  admin: "Administrator",
  editor: "Editor",
  employee: "Employee",
  owner: "Owner",
  viewer: "Viewer",
};

export const restrictedPermissionsByRole: Partial<
  Record<WorkspaceRole, Permission[]>
> = {
  employee: ["knowledge.manage"],
};

export function roleAllowsPermission(
  role: WorkspaceRole,
  permission: Permission
) {
  return !restrictedPermissionsByRole[role]?.includes(permission);
}

export function getDefaultPermissions(role: WorkspaceRole) {
  return new Set(defaultPermissionsByRole[role]);
}

export function getEffectivePermissions(
  role: WorkspaceRole,
  overrides: ReadonlyArray<{ effect: "grant" | "deny"; permission: string }>,
  isGuest = false
) {
  const permissions = isGuest
    ? new Set<Permission>()
    : getDefaultPermissions(role);

  if (isGuest) {
    permissions.add("chat.read");
    permissions.add("chat.write");
  }

  for (const override of overrides) {
    if (!permissionCatalog.some(({ key }) => key === override.permission)) {
      continue;
    }

    const permission = override.permission as Permission;
    if (override.effect === "grant") {
      permissions.add(permission);
    } else {
      permissions.delete(permission);
    }
  }

  for (const permission of restrictedPermissionsByRole[role] ?? []) {
    permissions.delete(permission);
  }

  return permissions;
}

export function hasPermission(
  role: WorkspaceRole,
  permission: Permission,
  overrides: ReadonlyArray<{ effect: "grant" | "deny"; permission: string }>,
  isGuest = false
) {
  return getEffectivePermissions(role, overrides, isGuest).has(permission);
}
