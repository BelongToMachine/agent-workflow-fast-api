"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  FileArchiveIcon,
  FileClockIcon,
  FileTextIcon,
  FileUpIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import {
  type ChangeEvent,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BackendRequestError, requestBackend } from "@/lib/backend/request";
import { cn } from "@/lib/utils";

type KnowledgeBase = {
  displayName: string;
  knowledgeBaseId: string;
};

type KnowledgeFile = {
  byteSize: number;
  createdAt: string;
  errorMessage: string | null;
  fileId: string;
  knowledgeBaseId: string;
  mimeType: string;
  originalName: string;
  status: string;
  updatedAt: string;
};

type KnowledgeBaseListResponse = {
  knowledgeBases: KnowledgeBase[];
};

type KnowledgeFileListResponse = {
  files: KnowledgeFile[];
};

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string, language: string, unknownDate: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return unknownDate;
  }
  return new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function statusLabel(
  status: string,
  t: (key: string) => string
) {
  if (status === "ready") {
    return t("settings.ready");
  }
  if (status === "processing") {
    return t("settings.processing");
  }
  if (status === "failed") {
    return t("settings.failed");
  }
  return t("settings.queued");
}

function statusVariant(status: string): "default" | "destructive" | "outline" {
  if (status === "ready") {
    return "default";
  }
  if (status === "failed") {
    return "destructive";
  }
  return "outline";
}

export function KnowledgeBaseFiles() {
  const { t, i18n } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFilesLoading, setIsFilesLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [deletingFileId, setDeletingFileId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<KnowledgeFile | null>(
    null
  );
  const [featureDisabled, setFeatureDisabled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedKnowledgeBase = useMemo(
    () =>
      knowledgeBases.find(
        ({ knowledgeBaseId }) => knowledgeBaseId === selectedKnowledgeBaseId
      ),
    [knowledgeBases, selectedKnowledgeBaseId]
  );

  const loadFiles = useCallback(async () => {
    if (!selectedKnowledgeBaseId) {
      setFiles([]);
      return;
    }

    setIsFilesLoading(true);
    setError(null);
    try {
      const data = await requestBackend<KnowledgeFileListResponse>(
        `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}/files`
      );
      setFeatureDisabled(false);
      setFiles(data.files);
    } catch (loadError) {
      if (
        loadError instanceof BackendRequestError &&
        loadError.status === 409
      ) {
        setFeatureDisabled(true);
      }
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("settings.unableToLoadKnowledgeFiles")
      );
      setFiles([]);
    } finally {
      setIsFilesLoading(false);
    }
  }, [selectedKnowledgeBaseId, t]);

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
      .catch((loadError) => {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t("settings.unableToLoadKnowledgeBases")
          );
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
    }, [t]);

  useEffect(() => {
    loadFiles().then(undefined, () => undefined);
  }, [loadFiles]);

  const refreshFiles = useCallback(async () => {
    await loadFiles();
  }, [loadFiles]);

  const requestDelete = useCallback((file: KnowledgeFile) => {
    setPendingDelete(file);
  }, []);

  const handleDialogOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !deletingFileId) {
        setPendingDelete(null);
      }
    },
    [deletingFileId]
  );

  const selectKnowledgeBase = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      const { knowledgeBaseId } = event.currentTarget.dataset;
      if (knowledgeBaseId) {
        setSelectedKnowledgeBaseId(knowledgeBaseId);
      }
    },
    []
  );

  const uploadFile = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file || !selectedKnowledgeBaseId) {
        return;
      }

      setIsUploading(true);
      setError(null);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const data = await requestBackend<{ file: KnowledgeFile }>(
          `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}/files`,
          { body: formData, method: "POST" }
        );
        setFeatureDisabled(false);
        setFiles((current) => [data.file, ...current]);
        toast.success(t("settings.fileUploaded"));
      } catch (uploadError) {
        const message =
          uploadError instanceof Error
            ? uploadError.message
            : t("settings.unableToUploadFile");
        setError(message);
        toast.error(message);
      } finally {
        setIsUploading(false);
      }
    },
    [selectedKnowledgeBaseId, t]
  );

  const deleteFile = useCallback(async () => {
    if (!pendingDelete || !selectedKnowledgeBaseId) {
      return;
    }

    const { fileId } = pendingDelete;
    setDeletingFileId(fileId);
    setError(null);
    try {
      await requestBackend(
        `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}/files/${encodeURIComponent(fileId)}`,
        { method: "DELETE" }
      );
      setFiles((current) => current.filter(({ fileId: id }) => id !== fileId));
      setPendingDelete(null);
      toast.success(t("settings.knowledgeFileDeleted"));
    } catch (deleteError) {
      const message =
        deleteError instanceof Error
          ? deleteError.message
          : t("settings.unableToDeleteFile");
      setError(message);
      toast.error(message);
    } finally {
      setDeletingFileId(null);
    }
  }, [pendingDelete, selectedKnowledgeBaseId, t]);

  const handleConfirmDelete = useCallback(
    async (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      await deleteFile();
    },
    [deleteFile]
  );

  if (isLoading) {
    return <LoadingState />;
  }

  if (error && knowledgeBases.length === 0) {
    return <EmptyState message={error} />;
  }

  return (
    <>
      <main className="min-h-full bg-background px-4 py-8 md:px-8 md:py-10">
        <div className="mx-auto max-w-6xl">
          <header className="mb-8 flex flex-col gap-5 border-b border-border/70 pb-7 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="mb-3 flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-[0.18em]">
                <FileArchiveIcon className="size-4 text-primary" />
                {t("settings.knowledgeIngestion")}
              </div>
              <h1 className="font-semibold text-3xl tracking-tight md:text-4xl">
                {t("settings.knowledgeBaseFiles")}
              </h1>
              <p className="mt-2 max-w-xl text-muted-foreground text-sm leading-6">
                {t("settings.ingestionDescription")}
              </p>
            </div>
            <Badge className="w-fit gap-1.5 px-3 py-1.5" variant="outline">
              <FileTextIcon className="size-3.5" />
              {t("settings.fileCount", {
                count: files.length,
                label: files.length === 1 ? t("common.file") : t("common.files"),
              })}
            </Badge>
          </header>

          <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
            <section className="rounded-2xl border border-border/70 bg-card/50 p-2 shadow-sm">
              <div className="px-3 py-3 text-muted-foreground text-xs uppercase tracking-[0.14em]">
                {t("settings.knowledgeBasesCount", {
                  count: knowledgeBases.length,
                })}
              </div>
              {knowledgeBases.length === 0 ? (
                <p className="px-3 py-6 text-muted-foreground text-sm">
                  {t("settings.noKnowledgeBases")}
                </p>
              ) : (
                <div className="space-y-1">
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
                            {isSelected
                              ? t("settings.fileCount", {
                                  count: files.length,
                                  label:
                                    files.length === 1
                                      ? t("common.file")
                                      : t("common.files"),
                                })
                              : t("settings.selectToManageFiles")}
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
                  <div className="flex flex-col gap-4 border-b border-border/70 p-5 md:flex-row md:items-start md:justify-between md:p-7">
                    <div className="flex items-start gap-3">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                        <DatabaseIcon className="size-5" />
                      </span>
                      <div>
                        <h2 className="font-semibold text-xl tracking-tight">
                          {selectedKnowledgeBase.displayName}
                        </h2>
                        <p className="mt-1 text-muted-foreground text-sm">
                          {t("settings.filesParsedDescription")}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        aria-label={t("settings.refreshKnowledgeFiles")}
                        disabled={isFilesLoading}
                        onClick={refreshFiles}
                        size="icon-sm"
                        variant="outline"
                      >
                        <RefreshCwIcon
                          className={cn(isFilesLoading && "animate-spin")}
                        />
                      </Button>
                      <Button asChild disabled={isUploading || featureDisabled}>
                        <label htmlFor="knowledge-file-upload">
                          {isUploading ? (
                            <LoaderCircleIcon className="animate-spin" />
                          ) : (
                            <FileUpIcon />
                          )}
                          {isUploading
                            ? t("settings.uploading")
                            : t("settings.uploadFile")}
                        </label>
                      </Button>
                      <input
                        accept=".csv,.json,.md,.pdf,.txt,.xlsx"
                        className="sr-only"
                        id="knowledge-file-upload"
                        onChange={uploadFile}
                        ref={fileInputRef}
                        type="file"
                      />
                    </div>
                  </div>

                  {featureDisabled ? (
                    <div className="flex gap-3 border-b border-amber-500/20 bg-amber-500/5 px-5 py-4 text-sm md:px-7">
                      <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-600" />
                      <p className="text-muted-foreground leading-6">
                        {t("settings.ingestionDisabled")}
                      </p>
                    </div>
                  ) : null}

                  <div className="p-5 md:p-7">
                    {isFilesLoading ? (
                      <FileListLoadingState />
                    ) : files.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-border/80 px-4 py-12 text-center">
                        <FileArchiveIcon className="mx-auto size-8 text-muted-foreground" />
                        <p className="mt-3 font-medium text-sm">
                          {t("settings.noFilesInKnowledgeBase")}
                        </p>
                        <p className="mt-1 text-muted-foreground text-sm">
                          {t("settings.uploadSupportedDocument")}
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {files.map((file) => (
                          <FileRow
                            deleting={deletingFileId === file.fileId}
                            file={file}
                            key={file.fileId}
                            onDelete={requestDelete}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                  {error ? (
                    <p className="border-t border-destructive/20 bg-destructive/5 px-5 py-3 text-destructive text-sm md:px-7">
                      {error}
                    </p>
                  ) : null}
                </>
              ) : (
                <EmptyState message="Select a knowledge base to manage files." />
              )}
            </section>
          </div>
        </div>
      </main>

      <AlertDialog
        onOpenChange={handleDialogOpenChange}
        open={pendingDelete !== null}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("settings.deleteKnowledgeFileTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `${pendingDelete.originalName} and its processed chunks will be permanently removed.`
                : t("settings.deleteKnowledgeFileDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deletingFileId !== null}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={deletingFileId !== null}
              onClick={handleConfirmDelete}
              variant="destructive"
            >
              {deletingFileId
                ? t("common.deleting")
                : t("settings.deleteFile")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function FileRow({
  deleting,
  file,
  onDelete,
}: {
  deleting: boolean;
  file: KnowledgeFile;
  onDelete: (file: KnowledgeFile) => void;
}) {
  const { t, i18n } = useTranslation();
  const isProcessing =
    file.status === "processing" || file.status === "pending";
  const handleDelete = useCallback(() => {
    onDelete(file);
  }, [file, onDelete]);

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-background/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          {file.status === "ready" ? (
            <CheckCircle2Icon className="size-4 text-emerald-600" />
          ) : isProcessing ? (
            <FileClockIcon className="size-4" />
          ) : (
            <FileTextIcon className="size-4" />
          )}
        </span>
        <div className="min-w-0">
          <p className="truncate font-medium text-sm">{file.originalName}</p>
          <p className="mt-1 text-muted-foreground text-xs">
            {formatBytes(file.byteSize)} · {t("common.uploaded")}{" "}
            {formatDate(file.createdAt, i18n.language, t("common.unknownDate"))}
          </p>
          {file.errorMessage ? (
            <p className="mt-1 text-destructive text-xs">{file.errorMessage}</p>
          ) : null}
        </div>
      </div>
      <div className="flex items-center gap-2 self-end sm:self-auto">
        <Badge variant={statusVariant(file.status)}>
          {isProcessing ? <LoaderCircleIcon className="animate-spin" /> : null}
          {statusLabel(file.status, t)}
        </Badge>
        <Button
          aria-label={t("settings.deleteFileAria", {
            name: file.originalName,
          })}
          disabled={deleting}
          onClick={handleDelete}
          size="icon-sm"
          variant="ghost"
        >
          <Trash2Icon />
        </Button>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <main className="min-h-full bg-background px-4 py-8 md:px-8 md:py-10">
      <div className="mx-auto max-w-6xl animate-pulse space-y-6">
        <div className="h-28 rounded-2xl bg-muted/50" />
        <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="h-80 rounded-2xl bg-muted/50" />
          <div className="h-80 rounded-2xl bg-muted/50" />
        </div>
      </div>
    </main>
  );
}

function FileListLoadingState() {
  return (
    <div className="animate-pulse space-y-2">
      <div className="h-16 rounded-xl bg-muted/50" />
      <div className="h-16 rounded-xl bg-muted/50" />
      <div className="h-16 rounded-xl bg-muted/50" />
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <main className="flex min-h-full items-center justify-center bg-background px-4 py-10">
      <div className="max-w-md rounded-2xl border border-border/70 bg-card/50 px-6 py-8 text-center shadow-sm">
        <FileArchiveIcon className="mx-auto size-8 text-muted-foreground" />
        <p className="mt-3 text-muted-foreground text-sm leading-6">
          {message}
        </p>
      </div>
    </main>
  );
}
