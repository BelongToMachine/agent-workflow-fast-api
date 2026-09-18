"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  CopyIcon,
  LinkIcon,
  LockKeyholeIcon,
  PowerIcon,
  RefreshCwIcon,
  SaveIcon,
  ShieldCheckIcon,
  UserRoundIcon,
  UserPlusIcon,
  UsersIcon,
  XCircleIcon,
} from "lucide-react";
import {
  type FormEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { InlineLoadingState } from "@/components/ui/loadingState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import {
  backendQueryKeys,
  useBackendIdentity,
  useBackendMutation,
  useBackendQuery,
} from "@/lib/backend/reactQuery";
import { useCurrentUserAccess } from "@/lib/auth/currentUser";
import { fastApiWorkspaceId } from "@/lib/backend/mode";
import {
  defaultPermissionsByRole,
  type Permission,
  permissionCatalog,
  roleAllowsPermission,
  roleLabels,
  type WorkspaceRole,
} from "@/lib/permissions";
import { cn } from "@/lib/utils";

type Member = {
  effectivePermissions: Permission[];
  email: string | null;
  id: string;
  name: string | null;
  overrides: { effect: "grant" | "deny"; permission: string }[];
  role: WorkspaceRole;
  status: "active" | "suspended";
  userId: string;
};

type AccessCandidate = {
  email: string | null;
  name: string | null;
  status: "active" | "suspended";
  userId: string;
};

type MembersResponse = {
  members: Member[];
  workspace: { id: string; name: string };
};

type AccessCandidatesResponse = {
  candidates: AccessCandidate[];
};

type InvitationStatus = "pending" | "expired" | "revoked" | "accepted";

type Invitation = {
  createdAt: string;
  email: string;
  expiresAt: string;
  invitationId: string;
  role: WorkspaceRole;
  status: InvitationStatus;
  workspaceId: string;
};

type InvitationsResponse = {
  invitations: Invitation[];
};

type InvitationResponse = Invitation & {
  activationUrl?: string | null;
};

const roleDescriptions: Record<WorkspaceRole, string> = {
  admin: "roles.adminDescription",
  editor: "roles.editorDescription",
  employee: "roles.employeeDescription",
  owner: "roles.ownerDescription",
  viewer: "roles.viewerDescription",
};

const invitationStatusLabels: Record<InvitationStatus, string> = {
  accepted: "settings.invitationAccepted",
  expired: "settings.invitationExpired",
  pending: "settings.invitationPending",
  revoked: "settings.invitationRevokedStatus",
};

const permissionTranslationKeys: Record<Permission, string> = {
  "members.read": "membersRead",
  "members.manage": "membersManage",
  "knowledge.read": "knowledgeRead",
  "knowledge.manage": "knowledgeManage",
  "chat.read": "chatRead",
  "chat.write": "chatWrite",
  "chat.delete": "chatDelete",
  "document.read": "documentRead",
  "document.write": "documentWrite",
  "audit.read": "auditRead",
  "agent.tool.products.search": "agentProductsSearch",
  "agent.tool.content.search": "agentContentSearch",
  "agent.tool.knowledge_bases.list": "agentKnowledgeBasesList",
  "agent.tool.knowledge_files.list": "agentKnowledgeFilesList",
  "agent.tool.knowledge_base.read": "agentKnowledgeBaseRead",
  "agent.tool.knowledge_file.read": "agentKnowledgeFileRead",
  "agent.tool.knowledge_file.extract": "agentKnowledgeFileExtract",
  "agent.tool.knowledge_base.search": "agentKnowledgeBaseSearch",
};

export function MemberPermissions() {
  const { t, i18n } = useTranslation();
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("employee");
  const [generatedInvitation, setGeneratedInvitation] =
    useState<InvitationResponse | null>(null);
  const [candidateId, setCandidateId] = useState<string>("");
  const [candidateRole, setCandidateRole] = useState<WorkspaceRole>("viewer");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [role, setRole] = useState<WorkspaceRole>("viewer");
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [pendingMemberId, setPendingMemberId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const identity = useBackendIdentity();
  const { hasPermission } = useCurrentUserAccess();
  const canManageMembers = hasPermission("members.manage");
  const membersQuery = useBackendQuery<MembersResponse>({
    path: "/api/admin/members",
    queryKey: backendQueryKeys.members(identity),
  });
  const candidatesQuery = useBackendQuery<AccessCandidatesResponse>({
    enabled: canManageMembers && membersQuery.isSuccess,
    path: "/api/admin/access-candidates",
    queryKey: backendQueryKeys.accessCandidates(identity),
  });
  const invitationsQuery = useBackendQuery<InvitationsResponse>({
    enabled: canManageMembers,
    path: `/api/v1/admin/auth/invitations?workspace_id=${encodeURIComponent(fastApiWorkspaceId)}`,
    queryKey: backendQueryKeys.invitations(identity),
    retry: false,
  });
  const saveMutation = useBackendMutation<
    { member?: Member },
    { memberId: string; permissions: Permission[]; role: WorkspaceRole }
  >({
    mutationKey: ["backend", "user", identity, "members", "update"],
    request: (variables) => ({
      init: {
        body: JSON.stringify(variables),
        method: "PATCH",
      },
      path: "/api/admin/members",
    }),
  });
  const addMutation = useBackendMutation<
    { member?: Member },
    { permissions: Permission[]; role: WorkspaceRole; userId: string }
  >({
    mutationKey: ["backend", "user", identity, "members", "add"],
    request: (variables) => ({
      init: {
        body: JSON.stringify(variables),
        method: "POST",
      },
      path: "/api/admin/members",
    }),
  });
  const statusMutation = useBackendMutation<
    { member?: Member },
    { memberId: string; status: "active" | "suspended" }
  >({
    mutationKey: ["backend", "user", identity, "members", "status"],
    request: ({ memberId, status }) => ({
      init: {
        body: JSON.stringify({ status }),
        method: "PATCH",
      },
      path: `/api/admin/members/${memberId}/status`,
    }),
  });
  const createInvitationMutation = useBackendMutation<
    InvitationResponse,
    { email: string; role: WorkspaceRole }
  >({
    mutationKey: ["backend", "user", identity, "invitations", "create"],
    request: (variables) => ({
      init: {
        body: JSON.stringify({
          email: variables.email,
          role: variables.role,
          workspaceId: fastApiWorkspaceId,
        }),
        method: "POST",
      },
      path: `/api/v1/admin/auth/invitations?workspace_id=${encodeURIComponent(fastApiWorkspaceId)}`,
    }),
  });
  const regenerateInvitationMutation = useBackendMutation<
    InvitationResponse,
    { invitationId: string }
  >({
    mutationKey: ["backend", "user", identity, "invitations", "regenerate"],
    request: ({ invitationId }) => ({
      init: { method: "POST" },
      path: `/api/v1/admin/auth/invitations/${encodeURIComponent(invitationId)}/regenerate?workspace_id=${encodeURIComponent(fastApiWorkspaceId)}`,
    }),
  });
  const revokeInvitationMutation = useBackendMutation<
    { invitationId: string; revoked: boolean },
    { invitationId: string }
  >({
    mutationKey: ["backend", "user", identity, "invitations", "revoke"],
    request: ({ invitationId }) => ({
      init: { method: "POST" },
      path: `/api/v1/admin/auth/invitations/${encodeURIComponent(invitationId)}/revoke?workspace_id=${encodeURIComponent(fastApiWorkspaceId)}`,
    }),
  });

  const { data, error: queryError, isLoading } = membersQuery;
  const { isPending: isSaving } = saveMutation;
  const { isPending: isAdding } = addMutation;
  const { isPending: isChangingStatus } = statusMutation;
  const { isPending: isCreatingInvitation } = createInvitationMutation;
  const { isPending: isRegeneratingInvitation } = regenerateInvitationMutation;
  const { isPending: isRevokingInvitation } = revokeInvitationMutation;
  const loadError = queryError
    ? queryError.status === 403
      ? t("settings.unableToManageMembers")
      : t("settings.unableToLoadMembers")
    : null;

  const selectedMember = data?.members.find(({ id }) => id === selectedId);
  const candidates = candidatesQuery.data?.candidates ?? [];
  const invitations = invitationsQuery.data?.invitations ?? [];

  useEffect(() => {
    if (data && !selectedId) {
      setSelectedId(data.members[0]?.id ?? null);
    }
  }, [data, selectedId]);

  useEffect(() => {
    if (!selectedMember) {
      return;
    }
    setRole(selectedMember.role);
    setPermissions(selectedMember.effectivePermissions);
    setIsDirty(false);
  }, [selectedMember]);

  const selectMember = useCallback(
    (memberId: string) => {
      if (isDirty) {
        setPendingMemberId(memberId);
        return;
      }
      setSelectedId(memberId);
    },
    [isDirty]
  );

  const handleMemberClick = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      const { currentTarget } = event;
      const { memberId } = currentTarget.dataset;
      if (memberId) {
        selectMember(memberId);
      }
    },
    [selectMember]
  );

  const discardAndSelectMember = useCallback(() => {
    if (!pendingMemberId) {
      return;
    }
    setIsDirty(false);
    setSelectedId(pendingMemberId);
    setPendingMemberId(null);
  }, [pendingMemberId]);

  const keepEditing = useCallback(() => {
    setPendingMemberId(null);
  }, []);

  const changeRole = useCallback(
    (nextRole: string) => {
      if (!canManageMembers) {
        return;
      }
      const roleValue = nextRole as WorkspaceRole;
      setRole(roleValue);
      setPermissions([...defaultPermissionsByRole[roleValue]]);
      setIsDirty(true);
    },
    [canManageMembers]
  );

  const togglePermission = useCallback(
    (permission: Permission) => {
      if (!canManageMembers || !roleAllowsPermission(role, permission)) {
        return;
      }
      setPermissions((current) =>
        current.includes(permission)
          ? current.filter((item) => item !== permission)
          : [...current, permission]
      );
      setIsDirty(true);
    },
    [canManageMembers, role]
  );

  const handlePermissionClick = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      const permission = event.currentTarget.dataset.permission as Permission;
      if (permission) {
        togglePermission(permission);
      }
    },
    [togglePermission]
  );

  const save = useCallback(async () => {
    if (!selectedMember || !canManageMembers) {
      return;
    }

    setError(null);

    try {
      const result = await saveMutation.mutateAsync({
        memberId: selectedMember.id,
        permissions,
        role,
      });
      if (result.member) {
        queryClient.setQueryData<MembersResponse>(
          backendQueryKeys.members(identity),
          (current) =>
            current
              ? {
                  ...current,
                  members: current.members.map((member) =>
                    member.id === result.member?.id ? result.member : member
                  ),
                }
              : current
        );
      }
      setIsDirty(false);
      toast.success(t("settings.permissionsUpdated"));
    } catch (saveError) {
      const message =
        saveError instanceof Error
          ? saveError.message
          : t("settings.unableToSavePermissions");
      setError(message);
      toast.error(message);
    }
  }, [canManageMembers, identity, permissions, queryClient, role, saveMutation, selectedMember, t]);

  const addMember = useCallback(async () => {
    if (!candidateId || !canManageMembers) {
      return;
    }

    setError(null);
    try {
      const result = await addMutation.mutateAsync({
        permissions: defaultPermissionsByRole[candidateRole],
        role: candidateRole,
        userId: candidateId,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: backendQueryKeys.members(identity) }),
        queryClient.invalidateQueries({
          queryKey: backendQueryKeys.accessCandidates(identity),
        }),
      ]);
      setCandidateId("");
      if (result.member) {
        setSelectedId(result.member.id);
      }
      toast.success(t("settings.memberAdded"));
    } catch (addError) {
      const message =
        addError instanceof Error ? addError.message : t("settings.unableToAddMember");
      setError(message);
      toast.error(message);
    }
  }, [addMutation, candidateId, candidateRole, canManageMembers, identity, queryClient, t]);

  const createInvitation = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const email = inviteEmail.trim();
      if (!email || !canManageMembers) {
        return;
      }

      setError(null);
      try {
        const result = await createInvitationMutation.mutateAsync({
          email,
          role: inviteRole,
        });
        setGeneratedInvitation(result);
        setInviteEmail("");
        await queryClient.invalidateQueries({
          queryKey: backendQueryKeys.invitations(identity),
        });
        toast.success(t("settings.invitationCreated"));
      } catch (invitationError) {
        const message =
          invitationError instanceof Error
            ? invitationError.message
            : t("settings.unableToCreateInvitation");
        setError(message);
        toast.error(message);
      }
    },
    [
      canManageMembers,
      createInvitationMutation,
      identity,
      inviteEmail,
      inviteRole,
      queryClient,
      t,
    ]
  );

  const copyInvitationLink = useCallback(async () => {
    const activationUrl = generatedInvitation?.activationUrl;
    if (!activationUrl) {
      return;
    }

    try {
      await navigator.clipboard.writeText(activationUrl);
      toast.success(t("settings.linkCopied"));
    } catch {
      setError(t("settings.copyFailedDescription"));
      toast.error(t("settings.copyFailed"));
    }
  }, [generatedInvitation, t]);

  const regenerateInvitation = useCallback(
    async (invitationId: string) => {
      if (!canManageMembers) {
        return;
      }

      setError(null);
      try {
        const result = await regenerateInvitationMutation.mutateAsync({
          invitationId,
        });
        setGeneratedInvitation(result);
        await queryClient.invalidateQueries({
          queryKey: backendQueryKeys.invitations(identity),
        });
        toast.success(t("settings.newInvitationCreated"));
      } catch (invitationError) {
        const message =
          invitationError instanceof Error
            ? invitationError.message
            : t("settings.unableToCreateNewInvitation");
        setError(message);
        toast.error(message);
      }
    },
    [
      canManageMembers,
      identity,
      queryClient,
      regenerateInvitationMutation,
      t,
    ]
  );

  const revokeInvitation = useCallback(
    async (invitationId: string) => {
      if (!canManageMembers || !window.confirm(t("settings.revokeInvitationConfirm"))) {
        return;
      }

      setError(null);
      try {
        await revokeInvitationMutation.mutateAsync({ invitationId });
        if (generatedInvitation?.invitationId === invitationId) {
          setGeneratedInvitation(null);
        }
        await queryClient.invalidateQueries({
          queryKey: backendQueryKeys.invitations(identity),
        });
        toast.success(t("settings.invitationRevoked"));
      } catch (invitationError) {
        const message =
          invitationError instanceof Error
            ? invitationError.message
            : t("settings.unableToRevokeInvitation");
        setError(message);
        toast.error(message);
      }
    },
    [
      canManageMembers,
      generatedInvitation,
      identity,
      queryClient,
      revokeInvitationMutation,
      t,
    ]
  );

  const changeMemberStatus = useCallback(async () => {
    if (!selectedMember || !canManageMembers) {
      return;
    }

    const nextStatus = selectedMember.status === "active" ? "suspended" : "active";
    setError(null);
    try {
      const result = await statusMutation.mutateAsync({
        memberId: selectedMember.id,
        status: nextStatus,
      });
      if (result.member) {
        queryClient.setQueryData<MembersResponse>(
          backendQueryKeys.members(identity),
          (current) =>
            current
              ? {
                  ...current,
                  members: current.members.map((member) =>
                    member.id === result.member?.id ? result.member : member
                  ),
                }
              : current
        );
      }
      toast.success(
        nextStatus === "active"
          ? t("settings.memberRestored")
          : t("settings.memberSuspended")
      );
    } catch (statusError) {
      const message =
        statusError instanceof Error
          ? statusError.message
          : t("settings.unableToUpdateMember");
      setError(message);
      toast.error(message);
    }
  }, [canManageMembers, identity, queryClient, selectedMember, statusMutation, t]);

  const visibleError = error ?? loadError;

  if (isLoading) {
    return <InlineLoadingState message={t("common.loading")} />;
  }

  if (visibleError && !data) {
    return <EmptyState message={visibleError} />;
  }

  if (!data || data.members.length === 0) {
    return <EmptyState message={t("settings.noMembers")} />;
  }

  return (
    <main className="min-h-full bg-background px-4 py-8 md:px-8 md:py-10">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-col gap-5 border-b border-border/70 pb-7 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="mb-3 flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-[0.18em]">
              <ShieldCheckIcon className="size-4 text-primary" />
              {t("settings.accessControl")}
            </div>
            <h1 className="font-semibold text-3xl tracking-tight md:text-4xl">
              {t("settings.workspacePermissions")}
            </h1>
            <p className="mt-2 max-w-xl text-muted-foreground text-sm leading-6">
              {t("settings.decideAccess")}
            </p>
          </div>
          <Badge className="w-fit gap-1.5 px-3 py-1.5" variant="outline">
            <UsersIcon className="size-3.5" />
            {data.workspace.name}
          </Badge>
        </header>

        {canManageMembers ? (
          <>
            <section className="mb-5 rounded-2xl border border-primary/20 bg-primary/[0.035] p-5 shadow-sm md:p-6">
              <div className="flex flex-col gap-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2 font-medium text-sm">
                      <LinkIcon className="size-4 text-primary" />
                      {t("settings.inviteTeammate")}
                    </div>
                    <p className="mt-1 max-w-2xl text-muted-foreground text-xs leading-5">
                      {t("settings.inviteDescription")}
                    </p>
                  </div>
                  <Badge className="w-fit" variant="secondary">
                    {t("settings.manualLink")}
                  </Badge>
                </div>

                <form className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto] md:items-end" onSubmit={createInvitation}>
                  <label className="grid gap-1.5 text-xs" htmlFor="invite-email">
                    {t("settings.workEmail")}
                    <Input
                      autoComplete="email"
                      disabled={isCreatingInvitation}
                      id="invite-email"
                      onChange={(event) => setInviteEmail(event.target.value)}
                      placeholder="colleague@company.com"
                      type="email"
                      value={inviteEmail}
                    />
                  </label>
                  <label className="grid gap-1.5 text-xs" htmlFor="invite-role">
                    {t("settings.accessLevel")}
                    <Select
                      disabled={isCreatingInvitation}
                      onValueChange={(value) => setInviteRole(value as WorkspaceRole)}
                      value={inviteRole}
                    >
                      <SelectTrigger
                        aria-label={t("settings.accessLevel")}
                        id="invite-role"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.entries(roleLabels)
                          .filter(([value]) => value !== "owner")
                          .map(([value]) => (
                            <SelectItem key={value} value={value}>
                              {t("roles." + value)}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <Button disabled={!inviteEmail.trim() || isCreatingInvitation} type="submit">
                    {isCreatingInvitation ? <Spinner /> : <LinkIcon />}
                    {isCreatingInvitation
                      ? t("settings.creating")
                      : t("settings.createLink")}
                  </Button>
                </form>

                {generatedInvitation ? (
                  <div className="rounded-xl border border-border/70 bg-background/80 p-4">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                      <label className="grid min-w-0 flex-1 gap-1.5 text-xs" htmlFor="generated-invite-link">
                        {t("settings.linkFor", {
                          email: generatedInvitation.email,
                        })}
                        <Input
                          className="font-mono text-xs"
                          id="generated-invite-link"
                          readOnly
                          value={
                            generatedInvitation.activationUrl ??
                            t("settings.linkUnavailable")
                          }
                        />
                      </label>
                      <Button
                        disabled={!generatedInvitation.activationUrl}
                        onClick={copyInvitationLink}
                        type="button"
                        variant="outline"
                      >
                        <CopyIcon />
                        {t("common.copyLink")}
                      </Button>
                    </div>
                    <p className="mt-2 text-amber-700 text-xs dark:text-amber-300">
                      {t("settings.invitationWarning")}
                    </p>
                  </div>
                ) : null}

                <div className="border-t border-border/60 pt-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="font-medium text-sm">
                        {t("settings.recentInvitations")}
                      </h3>
                      <p className="mt-1 text-muted-foreground text-xs">
                        {t("settings.invitationsNotShown")}
                      </p>
                    </div>
                    {invitationsQuery.isFetching ? (
                      <span className="flex items-center gap-2 text-muted-foreground text-xs">
                        <Spinner className="size-3" />
                        {t("settings.invitationsRefresh")}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 space-y-2">
                    {invitations.length === 0 ? (
                      <p className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-muted-foreground text-xs">
                        {t("settings.noInvitations")}
                      </p>
                    ) : (
                      invitations.map((invitation) => {
                        const canRegenerate =
                          invitation.status === "pending" ||
                          invitation.status === "expired" ||
                          invitation.status === "revoked";
                        return (
                          <div
                            className="flex flex-col gap-3 rounded-xl border border-border/60 bg-background/60 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                            key={invitation.invitationId}
                          >
                            <div className="min-w-0">
                              <p className="truncate font-medium text-sm">{invitation.email}</p>
                              <p className="mt-1 text-muted-foreground text-xs">
                                {t("roles." + invitation.role)} ·{" "}
                                {t("common.expires")}{" "}
                                {new Intl.DateTimeFormat(
                                  i18n.language === "zh" ? "zh-CN" : "en-US"
                                ).format(new Date(invitation.expiresAt))}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Badge variant={invitation.status === "pending" ? "secondary" : "outline"}>
                                {t(invitationStatusLabels[invitation.status])}
                              </Badge>
                              {canRegenerate ? (
                                <Button
                                  disabled={isRegeneratingInvitation || isRevokingInvitation}
                                  onClick={() => regenerateInvitation(invitation.invitationId)}
                                  size="sm"
                                  type="button"
                                  variant="outline"
                                >
                                  {isRegeneratingInvitation ? (
                                    <Spinner />
                                  ) : (
                                    <RefreshCwIcon />
                                  )}
                                  {t("settings.newLink")}
                                </Button>
                              ) : null}
                              {invitation.status === "pending" ? (
                                <Button
                                  disabled={isRegeneratingInvitation || isRevokingInvitation}
                                  onClick={() => revokeInvitation(invitation.invitationId)}
                                  size="sm"
                                  type="button"
                                  variant="ghost"
                                >
                                  {isRevokingInvitation ? (
                                    <Spinner />
                                  ) : (
                                    <XCircleIcon />
                                  )}
                                  {t("settings.revoke")}
                                </Button>
                              ) : null}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                  {invitationsQuery.error ? (
                    <p className="mt-3 text-destructive text-xs">
                      {t("settings.unableToLoadInvitations")}
                    </p>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="mb-5 rounded-2xl border border-border/70 bg-card/50 p-5 shadow-sm md:p-6">
              <div className="flex flex-col gap-4 md:flex-row md:items-end">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-medium text-sm">
                    <UserPlusIcon className="size-4 text-primary" />
                    {t("settings.addRegisteredUser")}
                  </div>
                  <p className="mt-1 text-muted-foreground text-xs leading-5">
                    {t("settings.registeredUserDescription")}
                  </p>
                  <Select
                    disabled={candidatesQuery.isLoading || candidates.length === 0 || isAdding}
                    onValueChange={setCandidateId}
                    value={candidateId}
                  >
                    <SelectTrigger
                      aria-label={t("settings.selectUser")}
                      className="mt-3"
                    >
                      <SelectValue
                        placeholder={
                          candidatesQuery.isLoading
                            ? t("settings.loadingUsers")
                            : candidates.length === 0
                              ? t("settings.noUsersWaiting")
                              : t("settings.selectUser")
                        }
                      />
                      {candidatesQuery.isLoading ? <Spinner className="size-3.5" /> : null}
                    </SelectTrigger>
                    <SelectContent>
                      {candidates.map((candidate) => (
                        <SelectItem key={candidate.userId} value={candidate.userId}>
                          {candidate.name || candidate.email || candidate.userId}
                          {candidate.name && candidate.email ? ` · ${candidate.email}` : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Select
                  disabled={!candidateId || isAdding}
                  onValueChange={(value) => setCandidateRole(value as WorkspaceRole)}
                  value={candidateRole}
                >
                  <SelectTrigger
                    aria-label={t("settings.newMemberRole")}
                    className="w-full md:w-40"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(roleLabels).map(([value]) => (
                      <SelectItem key={value} value={value}>
                        {t("roles." + value)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button disabled={!candidateId || isAdding} onClick={addMember}>
                  {isAdding ? <Spinner /> : <UserPlusIcon />}
                  {isAdding ? t("settings.adding") : t("settings.addMember")}
                </Button>
              </div>
              {candidatesQuery.error ? (
                <p className="mt-3 text-destructive text-xs">
                  {t("settings.unableToLoadWaitingUsers")}
                </p>
              ) : null}
            </section>
          </>
        ) : null}

        {!canManageMembers ? (
          <p className="mb-5 rounded-xl border border-border/70 bg-muted/30 px-4 py-3 text-muted-foreground text-sm">
            {t("settings.viewOnlyMembers")}
          </p>
        ) : null}

        {pendingMemberId ? (
          <div className="mb-5 flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
            <span>
              {t("settings.unsavedChangesDiscarded")}
            </span>
            <div className="flex items-center gap-2">
              <Button onClick={keepEditing} size="sm" variant="ghost">
                {t("settings.keepEditing")}
              </Button>
              <Button
                onClick={discardAndSelectMember}
                size="sm"
                variant="outline"
              >
                {t("settings.discardChanges")}
              </Button>
            </div>
          </div>
        ) : null}

        <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
          <section className="rounded-2xl border border-border/70 bg-card/50 p-2 shadow-sm">
            <div className="px-3 py-3 text-muted-foreground text-xs uppercase tracking-[0.14em]">
              {t("settings.membersCount", { count: data.members.length })}
            </div>
            <div className="space-y-1">
              {data.members.map((member) => {
                const isSelected = member.id === selectedId;
                return (
                  <button
                    aria-pressed={isSelected}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors",
                      isSelected
                        ? "bg-primary/10 text-foreground"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                    )}
                    data-member-id={member.id}
                    key={member.id}
                    onClick={handleMemberClick}
                    type="button"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                      <UserRoundIcon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-sm">
                        {member.name || member.email}
                      </span>
                      {member.name ? (
                        <span className="block truncate text-muted-foreground text-xs">
                          {member.email}
                        </span>
                      ) : null}
                    </span>
                    <span className="text-muted-foreground text-[11px]">
                      {t("roles." + member.role)}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="rounded-2xl border border-border/70 bg-card/50 shadow-sm">
            {selectedMember ? (
              <>
                <div className="flex flex-col gap-5 border-b border-border/70 p-5 md:flex-row md:items-start md:justify-between md:p-7">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="font-semibold text-xl tracking-tight">
                        {selectedMember.name || selectedMember.email}
                      </h2>
                      {isDirty ? (
                        <Badge variant="secondary">{t("settings.unsaved")}</Badge>
                      ) : null}
                    </div>
                    <p className="mt-1 text-muted-foreground text-sm">
                      {selectedMember.name
                        ? selectedMember.email
                        : t("settings.workspaceMember")}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      disabled={!canManageMembers || isChangingStatus || isSaving}
                      onClick={changeMemberStatus}
                      variant="outline"
                    >
                      {isChangingStatus ? <Spinner /> : <PowerIcon />}
                      {isChangingStatus
                        ? t("settings.updating")
                        : selectedMember.status === "active"
                          ? t("settings.suspend")
                          : t("settings.restoreMember")}
                    </Button>
                    <Select
                      disabled={!canManageMembers || isSaving || isChangingStatus}
                      onValueChange={changeRole}
                      value={role}
                    >
                      <SelectTrigger
                        aria-label={t("settings.memberRole")}
                        className="w-40"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.entries(roleLabels).map(([value]) => (
                          <SelectItem key={value} value={value}>
                            {t("roles." + value)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      disabled={!canManageMembers || !isDirty || isSaving}
                      onClick={save}
                    >
                      {isSaving ? <Spinner /> : <SaveIcon />}
                      {isSaving ? t("common.saving") : t("common.saveChanges")}
                    </Button>
                  </div>
                </div>

                <div className="grid gap-8 p-5 md:p-7 xl:grid-cols-[220px_minmax(0,1fr)]">
                  <div>
                    <div className="flex items-center gap-2 font-medium text-sm">
                      <LockKeyholeIcon className="size-4 text-primary" />
                      {t("settings.roleBaseline")}
                    </div>
                    <p className="mt-2 text-muted-foreground text-sm leading-6">
                      {t(roleDescriptions[role])}
                    </p>
                    <p className="mt-4 text-muted-foreground text-xs leading-5">
                      {t("settings.roleBaselineDescription")}
                    </p>
                  </div>

                  <div className="grid gap-7">
                    {[
                      {
                        key: "workspace",
                        permissions: permissionCatalog.filter(({ key }) =>
                          !key.startsWith("agent.tool.")
                        ),
                        title: null,
                        description: null,
                      },
                      {
                        key: "agentTools",
                        permissions: permissionCatalog.filter(({ key }) =>
                          key.startsWith("agent.tool.")
                        ),
                        title: t("settings.agentToolPermissions"),
                        description: t("settings.agentToolPermissionsDescription"),
                      },
                    ].map((group) => (
                      <div className="grid gap-2 sm:grid-cols-2" key={group.key}>
                        {group.title ? (
                          <div className="sm:col-span-2">
                            <h3 className="font-medium text-sm">{group.title}</h3>
                            <p className="mt-1 text-muted-foreground text-xs leading-5">
                              {group.description}
                            </p>
                          </div>
                        ) : null}
                        {group.permissions.map(({ key }) => {
                          const enabled = permissions.includes(key);
                          const isAllowed = roleAllowsPermission(role, key);
                          const permissionKey = permissionTranslationKeys[key];
                          return (
                            <button
                              aria-pressed={enabled}
                              className={cn(
                                "group flex min-h-20 items-start gap-3 rounded-xl border p-4 text-left transition-colors",
                                enabled
                                  ? "border-primary/30 bg-primary/[0.06]"
                                  : "border-border/70 bg-background/40 hover:bg-muted/40"
                              )}
                              data-permission={key}
                              disabled={!canManageMembers || !isAllowed}
                              key={key}
                              onClick={handlePermissionClick}
                              type="button"
                            >
                              <span
                                className={cn(
                                  "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border transition-colors",
                                  enabled
                                    ? "border-primary bg-primary text-primary-foreground"
                                    : "border-border text-transparent group-hover:border-muted-foreground"
                                )}
                              >
                                <CheckIcon className="size-3.5" />
                              </span>
                              <span>
                                <span className="block font-medium text-sm">
                                  {t("permissions." + permissionKey + ".label")}
                                </span>
                                <span className="mt-1 block text-muted-foreground text-xs leading-5">
                                  {t(
                                    "permissions." +
                                      permissionKey +
                                      ".description"
                                  )}
                                </span>
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
                {visibleError ? (
                  <p className="border-t border-destructive/20 bg-destructive/5 px-5 py-3 text-destructive text-sm md:px-7">
                    {visibleError}
                  </p>
                ) : null}
              </>
            ) : null}
          </section>
        </div>
      </div>
    </main>
  );
}

function EmptyState({ message }: { message: string }) {
  const { t } = useTranslation();

  return (
    <main className="grid min-h-full place-items-center bg-background px-6">
      <div className="max-w-md text-center">
        <ShieldCheckIcon className="mx-auto mb-4 size-8 text-muted-foreground" />
        <h1 className="font-semibold text-xl">
          {t("settings.permissionsUnavailable")}
        </h1>
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          {message}
        </p>
      </div>
    </main>
  );
}
