"use client";

import {
  AlertTriangleIcon,
  DatabaseIcon,
  PlusIcon,
  SaveIcon,
  Trash2Icon,
} from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alertDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { InlineLoadingState } from "@/components/ui/loadingState";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentUserAccess } from "@/lib/auth/currentUser";
import { requestBackend } from "@/lib/backend/request";
import { cn } from "@/lib/utils";

type KnowledgeBase = {
  displayName: string;
  knowledgeBaseId: string;
  sourceType?: string;
};

type KnowledgeBaseListResponse = {
  knowledgeBases: KnowledgeBase[];
};

export function KnowledgeBaseManagement() {
  const { t } = useTranslation();
  const { hasPermission } = useCurrentUserAccess();
  const canManageKnowledgeBases = hasPermission("knowledge.manage");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [newKnowledgeBaseName, setNewKnowledgeBaseName] = useState("");
  const [editedKnowledgeBaseName, setEditedKnowledgeBaseName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreatingKnowledgeBase, setIsCreatingKnowledgeBase] = useState(false);
  const [isUpdatingKnowledgeBase, setIsUpdatingKnowledgeBase] = useState(false);
  const [deletingKnowledgeBaseId, setDeletingKnowledgeBaseId] = useState<
    string | null
  >(null);
  const [pendingKnowledgeBaseDelete, setPendingKnowledgeBaseDelete] =
    useState<KnowledgeBase | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    requestBackend<KnowledgeBaseListResponse>("/api/knowledge-bases")
      .then((data) => {
        if (cancelled) {
          return;
        }
        setKnowledgeBases(data.knowledgeBases);
        setSelectedKnowledgeBaseId(
          data.knowledgeBases[0]?.knowledgeBaseId ?? ""
        );
      })
      .catch((loadError: Error) => {
        if (!cancelled) {
          setError(loadError.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedKnowledgeBase = knowledgeBases.find(
    ({ knowledgeBaseId }) => knowledgeBaseId === selectedKnowledgeBaseId
  );

  useEffect(() => {
    setEditedKnowledgeBaseName(selectedKnowledgeBase?.displayName ?? "");
  }, [selectedKnowledgeBase]);

  const selectKnowledgeBase = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      const { knowledgeBaseId } = event.currentTarget.dataset;
      if (knowledgeBaseId) {
        setSelectedKnowledgeBaseId(knowledgeBaseId);
      }
    },
    []
  );

  const handleNewKnowledgeBaseNameChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      setNewKnowledgeBaseName(event.target.value);
    },
    []
  );

  const handleEditedKnowledgeBaseNameChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      setEditedKnowledgeBaseName(event.target.value);
    },
    []
  );

  const createKnowledgeBase = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManageKnowledgeBases) {
        return;
      }

      const displayName = newKnowledgeBaseName.trim();
      if (!displayName) {
        setError(t("settings.enterNewKnowledgeBaseName"));
        return;
      }

      setIsCreatingKnowledgeBase(true);
      setError(null);
      try {
        const createdKnowledgeBase = await requestBackend<KnowledgeBase>(
          "/api/knowledge-bases",
          {
            body: JSON.stringify({ displayName, sourceType: "manual" }),
            method: "POST",
          }
        );
        setKnowledgeBases((current) => [createdKnowledgeBase, ...current]);
        setSelectedKnowledgeBaseId(createdKnowledgeBase.knowledgeBaseId);
        setNewKnowledgeBaseName("");
        toast.success(t("settings.knowledgeBaseCreated"));
      } catch (createError) {
        const message =
          createError instanceof Error
            ? createError.message
            : t("settings.unableToCreateKnowledgeBase");
        setError(message);
        toast.error(message);
      } finally {
        setIsCreatingKnowledgeBase(false);
      }
    },
    [canManageKnowledgeBases, newKnowledgeBaseName, t]
  );

  const renameKnowledgeBase = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManageKnowledgeBases) {
        return;
      }

      const displayName = editedKnowledgeBaseName.trim();
      if (!selectedKnowledgeBaseId || !displayName) {
        setError(t("settings.enterKnowledgeBaseName"));
        return;
      }

      setIsUpdatingKnowledgeBase(true);
      setError(null);
      try {
        const updatedKnowledgeBase = await requestBackend<KnowledgeBase>(
          `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}`,
          {
            body: JSON.stringify({
              displayName,
              sourceType: selectedKnowledgeBase?.sourceType ?? "manual",
            }),
            method: "PATCH",
          }
        );
        setKnowledgeBases((current) =>
          current.map((knowledgeBase) =>
            knowledgeBase.knowledgeBaseId ===
            updatedKnowledgeBase.knowledgeBaseId
              ? { ...knowledgeBase, ...updatedKnowledgeBase }
              : knowledgeBase
          )
        );
        setEditedKnowledgeBaseName(updatedKnowledgeBase.displayName);
        toast.success(t("settings.knowledgeBaseRenamed"));
      } catch (updateError) {
        const message =
          updateError instanceof Error
            ? updateError.message
            : t("settings.unableToRenameKnowledgeBase");
        setError(message);
        toast.error(message);
      } finally {
        setIsUpdatingKnowledgeBase(false);
      }
    },
    [
      canManageKnowledgeBases,
      editedKnowledgeBaseName,
      selectedKnowledgeBase,
      selectedKnowledgeBaseId,
      t,
    ]
  );

  const deleteKnowledgeBase = useCallback(async () => {
    if (!pendingKnowledgeBaseDelete || !canManageKnowledgeBases) {
      return;
    }

    const { knowledgeBaseId } = pendingKnowledgeBaseDelete;
    setDeletingKnowledgeBaseId(knowledgeBaseId);
    setError(null);
    try {
      await requestBackend(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`,
        { method: "DELETE" }
      );

      const remainingKnowledgeBases = knowledgeBases.filter(
        ({ knowledgeBaseId: id }) => id !== knowledgeBaseId
      );
      setKnowledgeBases(remainingKnowledgeBases);
      setSelectedKnowledgeBaseId(
        remainingKnowledgeBases[0]?.knowledgeBaseId ?? ""
      );
      setPendingKnowledgeBaseDelete(null);
      toast.success(t("settings.knowledgeBaseDeleted"));
    } catch (deleteError) {
      const message =
        deleteError instanceof Error
          ? deleteError.message
          : t("settings.unableToDeleteKnowledgeBase");
      setError(message);
      toast.error(message);
    } finally {
      setDeletingKnowledgeBaseId(null);
    }
  }, [canManageKnowledgeBases, knowledgeBases, pendingKnowledgeBaseDelete, t]);

  const requestKnowledgeBaseDelete = useCallback(() => {
    if (selectedKnowledgeBase && canManageKnowledgeBases) {
      setPendingKnowledgeBaseDelete(selectedKnowledgeBase);
    }
  }, [canManageKnowledgeBases, selectedKnowledgeBase]);

  const handleKnowledgeBaseDeleteDialogChange = useCallback(
    (open: boolean) => {
      if (!open && !deletingKnowledgeBaseId) {
        setPendingKnowledgeBaseDelete(null);
      }
    },
    [deletingKnowledgeBaseId]
  );

  const handleConfirmKnowledgeBaseDelete = useCallback(
    async (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      await deleteKnowledgeBase();
    },
    [deleteKnowledgeBase]
  );

  if (isLoading) {
    return <InlineLoadingState message={t("common.loading")} />;
  }

  if (error && knowledgeBases.length === 0) {
    return <EmptyState message={error} />;
  }

  return (
    <>
      {error ? (
        <div
          aria-live="polite"
          className="mb-5 flex items-start gap-3 rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-destructive text-sm"
          role="alert"
        >
          <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <section className="rounded-2xl border border-border/70 bg-card/50 p-2 shadow-sm">
          <div className="flex items-center justify-between px-3 py-3">
            <div className="text-muted-foreground text-xs uppercase tracking-[0.14em]">
              {t("settings.knowledgeBasesCount", {
                count: knowledgeBases.length,
              })}
            </div>
            <DatabaseIcon className="size-4 text-muted-foreground" />
          </div>
          <form
            className="flex gap-2 border-b border-border/70 px-2 pb-3"
            onSubmit={createKnowledgeBase}
          >
            <Label className="sr-only" htmlFor="new-knowledge-base-name">
              {t("settings.newKnowledgeBase")}
            </Label>
            <Input
              className="min-w-0"
              disabled={!canManageKnowledgeBases || isCreatingKnowledgeBase}
              id="new-knowledge-base-name"
              onChange={handleNewKnowledgeBaseNameChange}
              placeholder={t("settings.newKnowledgeBase")}
              value={newKnowledgeBaseName}
            />
            <Button
              aria-label={t("settings.createKnowledgeBase")}
              disabled={!canManageKnowledgeBases || isCreatingKnowledgeBase}
              size="icon-sm"
              type="submit"
            >
              {isCreatingKnowledgeBase ? <Spinner /> : <PlusIcon />}
            </Button>
          </form>
          {knowledgeBases.length === 0 ? (
            <p className="px-3 py-6 text-muted-foreground text-sm">
              {t("settings.noKnowledgeBases")}
            </p>
          ) : (
            <div className="space-y-1 pt-2">
              {knowledgeBases.map((knowledgeBase) => {
                const isSelected =
                  knowledgeBase.knowledgeBaseId === selectedKnowledgeBaseId;
                return (
                  <button
                    aria-pressed={isSelected}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors",
                      isSelected
                        ? "bg-primary/10 text-foreground"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                    )}
                    data-knowledge-base-id={knowledgeBase.knowledgeBaseId}
                    key={knowledgeBase.knowledgeBaseId}
                    onClick={selectKnowledgeBase}
                    type="button"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                      <DatabaseIcon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-sm">
                        {knowledgeBase.displayName}
                      </span>
                      <span className="block text-muted-foreground text-xs">
                        {t("settings.knowledgeBaseManagement")}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-border/70 bg-card/50 shadow-sm">
          {selectedKnowledgeBase ? (
            <>
              <div className="border-b border-border/70 p-5 md:p-7">
                <div className="flex items-start gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <DatabaseIcon className="size-5" />
                  </span>
                  <div>
                    <p className="text-muted-foreground text-xs uppercase tracking-[0.14em]">
                      {t("settings.knowledgeBaseManagement")}
                    </p>
                    <h2 className="mt-2 font-semibold text-xl tracking-tight">
                      {selectedKnowledgeBase.displayName}
                    </h2>
                    <p className="mt-1 text-muted-foreground text-sm">
                      {t("settings.knowledgeBaseManagementSelectedDescription")}
                    </p>
                  </div>
                </div>
              </div>

              <div className="p-5 md:p-7">
                <form
                  className="flex flex-col gap-2 sm:flex-row sm:items-end"
                  onSubmit={renameKnowledgeBase}
                >
                  <div className="grid flex-1 gap-2">
                    <Label htmlFor="knowledge-base-name">
                      {t("settings.knowledgeBaseName")}
                    </Label>
                    <Input
                      id="knowledge-base-name"
                      onChange={handleEditedKnowledgeBaseNameChange}
                      disabled={!canManageKnowledgeBases || isUpdatingKnowledgeBase}
                      value={editedKnowledgeBaseName}
                    />
                  </div>
                  <Button
                    disabled={!canManageKnowledgeBases || isUpdatingKnowledgeBase}
                    type="submit"
                  >
                    {isUpdatingKnowledgeBase ? <Spinner /> : <SaveIcon />}
                    {isUpdatingKnowledgeBase
                      ? t("common.saving")
                      : t("settings.saveName")}
                  </Button>
                  <Button
                    disabled={
                      !canManageKnowledgeBases || deletingKnowledgeBaseId !== null
                    }
                    onClick={requestKnowledgeBaseDelete}
                    type="button"
                    variant="destructive"
                  >
                    {deletingKnowledgeBaseId ? <Spinner /> : <Trash2Icon />}
                    {deletingKnowledgeBaseId ? t("common.deleting") : t("common.delete")}
                  </Button>
                </form>
              </div>
            </>
          ) : (
            <EmptyState message={t("settings.selectKnowledgeBaseToManage")} />
          )}
        </section>
      </div>

      <AlertDialog
        onOpenChange={handleKnowledgeBaseDeleteDialogChange}
        open={pendingKnowledgeBaseDelete !== null}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("settings.deleteKnowledgeBaseTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingKnowledgeBaseDelete
                ? t("settings.deleteKnowledgeBaseDescriptionWithName", {
                    name: pendingKnowledgeBaseDelete.displayName,
                  })
                : t("settings.deleteKnowledgeBaseDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deletingKnowledgeBaseId !== null}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={deletingKnowledgeBaseId !== null}
              onClick={handleConfirmKnowledgeBaseDelete}
              variant="destructive"
            >
              {deletingKnowledgeBaseId ? <Spinner /> : null}
              {deletingKnowledgeBaseId
                ? t("common.deleting")
                : t("settings.deleteKnowledgeBase")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-80 flex-col items-center justify-center rounded-2xl border border-border/70 bg-card/50 px-6 py-10 text-center shadow-sm">
      <DatabaseIcon className="size-8 text-muted-foreground" />
      <p className="mt-3 max-w-md text-muted-foreground text-sm leading-6">
        {message}
      </p>
    </div>
  );
}
