"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  FileArchiveIcon,
  FileIcon,
  FileUpIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  PlusIcon,
  UploadCloudIcon,
  XIcon,
} from "lucide-react";
import {
  type DragEvent,
  type KeyboardEvent,
  type ChangeEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineLoadingState } from "@/components/ui/loadingState";
import {
  BackendRequestError,
  requestBackend,
  requestBackendUpload,
} from "@/lib/backend/request";
import { Link } from "@/lib/router";
import { cn } from "@/lib/utils";
import { waitForAutomatedIngestion } from "./automatedIngestion.mjs";
import { KnowledgeFileLibrary } from "./knowledgeFileLibrary";

const ACCEPTED_EXTENSIONS = [
  ".xlsx",
  ".csv",
  ".json",
  ".md",
  ".txt",
  ".pdf",
  ".ppt",
  ".pptx",
] as const;
const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

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
  storageProvider: string;
  updatedAt: string;
};

type UploadItemStatus = "ready" | "uploading" | "uploaded" | "failed";

type UploadItem = {
  errorMessage?: string;
  id: string;
  file: File;
  progress: number;
  status: UploadItemStatus;
};

type AutomationStage =
  | "idle"
  | "uploading"
  | "parsing"
  | "chunking"
  | "embedding"
  | "complete"
  | "failed";

type KnowledgeBaseListResponse = {
  knowledgeBases: KnowledgeBase[];
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

function fileExtension(fileName: string) {
  const extension = fileName.slice(fileName.lastIndexOf(".")).toLowerCase();
  return extension === fileName ? "" : extension;
}

function isAcceptedFile(file: File) {
  return ACCEPTED_EXTENSIONS.includes(
    fileExtension(file.name) as (typeof ACCEPTED_EXTENSIONS)[number]
  );
}

function fileKind(fileName: string) {
  const extension = fileExtension(fileName).replace(".", "").toUpperCase();
  return extension || "FILE";
}

function uploadItemId(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`;
}

export function UploadPage() {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeTab, setActiveTab] = useState<"manual" | "automation">("manual");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isLoadingBases, setIsLoadingBases] = useState(true);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [storedFilesRefreshKey, setStoredFilesRefreshKey] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [featureDisabled, setFeatureDisabled] = useState(false);

  useEffect(() => {
    let cancelled = false;

    requestBackend<KnowledgeBaseListResponse>("/api/knowledge-bases")
      .then((data) => {
        if (cancelled) {
          return;
        }
        setKnowledgeBases(data.knowledgeBases);
        setSelectedKnowledgeBaseId(data.knowledgeBases[0]?.knowledgeBaseId ?? "");
        setFeatureDisabled(false);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        if (error instanceof BackendRequestError && error.status === 409) {
          setFeatureDisabled(true);
        }
        setLoadError(
          error instanceof Error ? error.message : t("upload.loadError")
        );
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingBases(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [t]);

  const addFiles = useCallback(
    (incomingFiles: File[]) => {
      const nextItems: UploadItem[] = [];
      const existingIds = new Set(items.map(({ id }) => id));

      for (const file of incomingFiles) {
        const id = uploadItemId(file);
        if (existingIds.has(id) || nextItems.some((item) => item.id === id)) {
          continue;
        }

        if (!isAcceptedFile(file)) {
          nextItems.push({
            errorMessage: t("upload.unsupportedType", { name: file.name }),
            file,
            id,
            progress: 0,
            status: "failed",
          });
          continue;
        }

        nextItems.push({ file, id, progress: 0, status: "ready" });
      }

      if (nextItems.length > 0) {
        setItems((current) => [...current, ...nextItems]);
      }
    },
    [items, t]
  );

  const handleFileChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      addFiles(Array.from(event.target.files ?? []));
      event.target.value = "";
    },
    [addFiles]
  );

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      addFiles(Array.from(event.dataTransfer.files));
    },
    [addFiles]
  );

  const handleDropzoneKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInputRef.current?.click();
      }
    },
    []
  );

  const removeItem = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const clearUploaded = useCallback(() => {
    setItems((current) => current.filter(({ status }) => status !== "uploaded"));
  }, []);

  const uploadFiles = useCallback(async () => {
    if (!selectedKnowledgeBaseId || isUploading) {
      return;
    }

    const readyItems = items.filter(({ status }) => status === "ready");
    if (readyItems.length === 0) {
      return;
    }

    setIsUploading(true);
    setLoadError(null);
    let uploadedCount = 0;

    for (const item of readyItems) {
      setItems((current) =>
          current.map((currentItem) =>
            currentItem.id === item.id
            ? {
                ...currentItem,
                errorMessage: undefined,
                progress: 0,
                status: "uploading",
              }
            : currentItem
        )
      );

      try {
        const formData = new FormData();
        formData.append("file", item.file);
        await requestBackendUpload<{ file: KnowledgeFile }>(
          `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}/files`,
          formData,
          (loaded, total) => {
            const progress = total
              ? Math.min(99, Math.round((loaded / total) * 100))
              : 0;
            setItems((current) =>
              current.map((currentItem) =>
                currentItem.id === item.id
                  ? { ...currentItem, progress }
                  : currentItem
              )
            );
          }
        );
        uploadedCount += 1;
        setItems((current) =>
          current.map((currentItem) =>
            currentItem.id === item.id
              ? { ...currentItem, progress: 100, status: "uploaded" }
              : currentItem
          )
        );
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : t("upload.uploadFailed");
        setItems((current) =>
          current.map((currentItem) =>
            currentItem.id === item.id
              ? { ...currentItem, errorMessage, status: "failed" }
              : currentItem
          )
        );
      }
    }

    setIsUploading(false);
    if (uploadedCount > 0) {
      setStoredFilesRefreshKey((current) => current + 1);
    }
    if (uploadedCount === readyItems.length) {
      toast.success(t("upload.allUploaded"));
    } else if (uploadedCount > 0) {
      toast.warning(t("upload.someFailed"));
    } else {
      toast.error(t("upload.someFailed"));
    }
  }, [isUploading, items, selectedKnowledgeBaseId, t]);

  const readyCount = items.filter(({ status }) => status === "ready").length;
  const uploadedCount = items.filter(({ status }) => status === "uploaded").length;
  const totalBytes = items.reduce((total, { file }) => total + file.size, 0);
  const progressItems = items.filter(({ status }) => status !== "failed");
  const progressTotalBytes = progressItems.reduce(
    (total, { file }) => total + file.size,
    0
  );
  const progressTransferredBytes = progressItems.reduce(
    (total, item) =>
      total +
      (item.status === "uploaded"
        ? item.file.size
        : item.status === "uploading"
          ? (item.file.size * item.progress) / 100
          : 0),
    0
  );
  const overallProgress = progressTotalBytes
    ? Math.min(
        100,
        Math.round((progressTransferredBytes / progressTotalBytes) * 100)
      )
    : 0;

  if (isLoadingBases) {
    return <InlineLoadingState fillViewport message={t("common.loading")} />;
  }

  return (
    <main className="min-h-full overflow-y-auto bg-background px-4 py-8 md:px-8 md:py-10">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-col gap-6 border-b border-border/70 pb-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <div className="mb-3 flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-[0.18em]">
              <span aria-hidden="true" className="size-2 rounded-full bg-primary" />
              {t("upload.eyebrow")}
            </div>
            <h1 className="text-balance font-semibold text-3xl tracking-[-0.04em] md:text-5xl">
              {t("upload.title")}
            </h1>
            <p className="mt-3 max-w-xl text-muted-foreground text-sm leading-7 md:text-base">
              {t(
                activeTab === "manual"
                  ? "upload.description"
                  : "upload.automationDescription"
              )}
            </p>
          </div>
          <div className="flex items-center gap-3 text-muted-foreground text-xs">
            <span className="font-mono text-foreground">01</span>
            <span aria-hidden="true" className="h-px w-8 bg-border" />
            <span>
              {t(
                activeTab === "manual"
                  ? "upload.stepLabel"
                  : "upload.automationStepLabel"
              )}
            </span>
          </div>
        </header>

        {loadError ? (
          <div
            aria-live="polite"
            className="mb-5 flex items-start gap-3 rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-destructive text-sm"
            role="alert"
          >
            <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
            <span>{loadError}</span>
          </div>
        ) : null}

        {featureDisabled ? (
          <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm">
            <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-600" />
            <span className="text-muted-foreground">{t("upload.backendDisabled")}</span>
          </div>
        ) : null}

        <div className="w-full">
          <div
            aria-label={t("upload.modeLabel")}
            className="mb-5 flex border-b border-border/70"
            onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
                return;
              }
              event.preventDefault();
              const nextTab =
                event.key === "Home"
                  ? "manual"
                  : event.key === "End"
                    ? "automation"
                    : activeTab === "manual"
                      ? "automation"
                      : "manual";
              setActiveTab(nextTab);
              document.getElementById(`upload-tab-${nextTab}`)?.focus();
            }}
            role="tablist"
          >
            {(["manual", "automation"] as const).map((tab) => (
              <button
                aria-controls={`upload-panel-${tab}`}
                aria-selected={activeTab === tab}
                className={cn(
                  "-mb-px min-h-11 border-b-2 px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  activeTab === tab
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
                id={`upload-tab-${tab}`}
                key={tab}
                onClick={() => setActiveTab(tab)}
                role="tab"
                tabIndex={activeTab === tab ? 0 : -1}
                type="button"
              >
                {t(tab === "manual" ? "upload.tabManual" : "upload.tabAutomation")}
              </button>
            ))}
          </div>

          <div
            aria-labelledby="upload-tab-manual"
            hidden={activeTab !== "manual"}
            id="upload-panel-manual"
            role="tabpanel"
            tabIndex={0}
          >
          <section className="w-full rounded-2xl border border-border/70 bg-card/50 shadow-[var(--shadow-card)]">
            <div className="border-b border-border/70 p-5 md:p-7">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-muted-foreground text-xs uppercase tracking-[0.16em]">
                    {t("upload.destinationLabel")}
                  </p>
                  <label className="mt-2 block">
                    <span className="sr-only">{t("upload.destinationLabel")}</span>
                    <select
                      aria-label={t("upload.destinationLabel")}
                      className="h-10 max-w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition-shadow focus:ring-2 focus:ring-ring"
                      disabled={knowledgeBases.length === 0 || isUploading}
                      onChange={(event) => setSelectedKnowledgeBaseId(event.target.value)}
                      value={selectedKnowledgeBaseId}
                    >
                      {knowledgeBases.length === 0 ? (
                        <option value="">{t("upload.noKnowledgeBase")}</option>
                      ) : null}
                      {knowledgeBases.map((knowledgeBase) => (
                        <option
                          key={knowledgeBase.knowledgeBaseId}
                          value={knowledgeBase.knowledgeBaseId}
                        >
                          {knowledgeBase.displayName}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <Badge className="w-fit gap-1.5 px-3 py-1.5" variant="outline">
                  <LockKeyholeIcon className="size-3.5" />
                  {t("upload.privateBadge")}
                </Badge>
              </div>
            </div>

            <div className="p-5 md:p-7">
              {knowledgeBases.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border/80 px-6 py-14 text-center">
                  <DatabaseIcon className="mx-auto size-8 text-muted-foreground" />
                  <p className="mt-3 font-medium text-sm">{t("upload.noKnowledgeBase")}</p>
                  <p className="mx-auto mt-2 max-w-sm text-muted-foreground text-sm leading-6">
                    {t("upload.noKnowledgeBaseDescription")}
                  </p>
                  <Button asChild className="mt-5" variant="outline">
                    <Link href="/settings/knowledge-bases">
                      <PlusIcon />
                      {t("upload.createKnowledgeBase")}
                    </Link>
                  </Button>
                </div>
              ) : (
                <>
                  <div
                    aria-describedby="upload-dropzone-hint"
                    aria-label={t("upload.dropTitle")}
                    className={cn(
                      "group relative flex min-h-72 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border border-dashed px-6 py-12 text-center outline-none transition-colors",
                      isDragging
                        ? "border-foreground bg-muted/70"
                        : "border-border/90 bg-background/35 hover:border-foreground/50 hover:bg-muted/30",
                      isUploading && "pointer-events-none opacity-70"
                    )}
                    onClick={() => fileInputRef.current?.click()}
                    onDragEnter={(event) => {
                      event.preventDefault();
                      setIsDragging(true);
                    }}
                    onDragLeave={(event) => {
                      event.preventDefault();
                      setIsDragging(false);
                    }}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={handleDrop}
                    onKeyDown={handleDropzoneKeyDown}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="mb-5 flex size-14 items-center justify-center rounded-full border border-border bg-muted/60 text-foreground transition-transform duration-300 group-hover:-translate-y-1">
                      <UploadCloudIcon className="size-6" strokeWidth={1.5} />
                    </div>
                    <h2 className="font-medium text-lg tracking-tight">{t("upload.dropTitle")}</h2>
                    <p className="mt-2 text-muted-foreground text-sm">{t("upload.dropDescription")}</p>
                    <Button className="mt-5" disabled={isUploading} type="button" variant="outline">
                      <FileUpIcon />
                      {t("upload.chooseFiles")}
                    </Button>
                    <p className="mt-5 max-w-sm text-muted-foreground text-xs leading-5" id="upload-dropzone-hint">
                      {t("upload.formats")}
                    </p>
                    <input
                      accept={ACCEPT_ATTRIBUTE}
                      className="sr-only"
                      disabled={isUploading}
                      multiple
                      onChange={handleFileChange}
                      ref={fileInputRef}
                      type="file"
                    />
                  </div>

                  <div className="mt-7 flex flex-col gap-3 border-b border-border/70 pb-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h2 className="font-medium text-sm">{t("upload.reviewTitle")}</h2>
                      <p className="mt-1 text-muted-foreground text-xs">{t("upload.reviewDescription")}</p>
                    </div>
                    {uploadedCount > 0 ? (
                      <Button disabled={isUploading} onClick={clearUploaded} size="sm" variant="ghost">
                        {t("upload.clearCompleted")}
                      </Button>
                    ) : null}
                  </div>

                  {items.length === 0 ? (
                    <div className="flex flex-col items-center px-4 py-10 text-center">
                      <FileArchiveIcon className="size-7 text-muted-foreground/70" />
                      <p className="mt-3 text-muted-foreground text-sm">{t("upload.emptyQueue")}</p>
                    </div>
                  ) : (
                    <div className="mt-4 space-y-2">
                      {items.map((item) => (
                        <UploadItemRow
                          item={item}
                          key={item.id}
                          onRemove={removeItem}
                          t={t}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {knowledgeBases.length > 0 ? (
              <div className="flex flex-col gap-4 border-t border-border/70 bg-muted/20 px-5 py-4 md:flex-row md:items-center md:justify-between md:px-7">
                <div className="min-w-0 flex-1 text-muted-foreground text-xs">
                  {isUploading ? (
                    <div className="max-w-sm space-y-2" role="status">
                      <div className="flex items-center justify-between gap-3">
                        <span>{t("upload.overallProgress")}</span>
                        <span className="font-mono text-foreground">{overallProgress}%</span>
                      </div>
                      <div
                        aria-label={t("upload.overallProgress")}
                        aria-valuemax={100}
                        aria-valuemin={0}
                        aria-valuenow={overallProgress}
                        className="h-1.5 overflow-hidden rounded-full bg-border"
                        role="progressbar"
                      >
                        <div
                          className="h-full rounded-full bg-primary transition-[width] duration-200"
                          style={{ width: `${overallProgress}%` }}
                        />
                      </div>
                    </div>
                  ) : items.length > 0 ? (
                    <>
                      {t("upload.queueSummary", { count: items.length })} · {formatBytes(totalBytes)}
                    </>
                  ) : (
                    t("upload.maxFileSize")
                  )}
                </div>
                <Button
                  disabled={readyCount === 0 || isUploading || !selectedKnowledgeBaseId}
                  onClick={uploadFiles}
                >
                  {isUploading ? <LoaderCircleIcon className="animate-spin" /> : <FileUpIcon />}
                  {isUploading
                    ? t("upload.uploading", { count: readyCount })
                    : t("upload.uploadAll", { count: readyCount })}
                </Button>
              </div>
            ) : null}
          </section>

          {selectedKnowledgeBaseId ? (
            <KnowledgeFileLibrary
              disabled={isUploading}
              knowledgeBaseId={selectedKnowledgeBaseId}
              refreshKey={storedFilesRefreshKey}
            />
          ) : null}
          </div>

          <div
            aria-labelledby="upload-tab-automation"
            hidden={activeTab !== "automation"}
            id="upload-panel-automation"
            role="tabpanel"
            tabIndex={0}
          >
            <AutomatedUploadPanel
              disabled={featureDisabled || knowledgeBases.length === 0}
              knowledgeBases={knowledgeBases}
              onUploaded={() => setStoredFilesRefreshKey((current) => current + 1)}
              selectedKnowledgeBaseId={selectedKnowledgeBaseId}
              setSelectedKnowledgeBaseId={setSelectedKnowledgeBaseId}
            />
          </div>
        </div>
      </div>
    </main>
  );
}

function AutomatedUploadPanel({
  disabled,
  knowledgeBases,
  onUploaded,
  selectedKnowledgeBaseId,
  setSelectedKnowledgeBaseId,
}: {
  disabled: boolean;
  knowledgeBases: KnowledgeBase[];
  onUploaded: () => void;
  selectedKnowledgeBaseId: string;
  setSelectedKnowledgeBaseId: (id: string) => void;
}) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [stage, setStage] = useState<AutomationStage>("idle");
  const [failedAt, setFailedAt] = useState<
    "uploading" | "parsing" | "chunking" | "embedding" | null
  >(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<{
    chunkCount: number;
    fileName: string;
    parsedDocumentId: string;
  } | null>(null);
  const isRunning = ["uploading", "parsing", "chunking", "embedding"].includes(stage);

  useEffect(
    () => () => {
      abortControllerRef.current?.abort();
    },
    []
  );

  const selectFile = (file: File | undefined) => {
    if (!file) {
      return;
    }
    setResult(null);
    setErrorMessage(null);
    setFailedAt(null);
    setUploadProgress(0);
    if (file.size > 100 * 1024 * 1024) {
      setSelectedFile(null);
      setStage("failed");
      setFailedAt("uploading");
      setErrorMessage(t("upload.fileTooLarge", { name: file.name }));
      return;
    }
    if (!isAcceptedFile(file)) {
      setSelectedFile(null);
      setStage("failed");
      setFailedAt("uploading");
      setErrorMessage(t("upload.unsupportedType", { name: file.name }));
      return;
    }
    setSelectedFile(file);
    setStage("idle");
  };

  const runAutomation = async () => {
    if (!selectedFile || !selectedKnowledgeBaseId || isRunning || disabled) {
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    let currentStage: "uploading" | "parsing" | "chunking" | "embedding" = "uploading";
    let didUpload = false;
    setErrorMessage(null);
    setResult(null);
    setFailedAt(null);
    setUploadProgress(0);
    setStage("uploading");

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const response = await requestBackendUpload<{ file: KnowledgeFile }>(
        `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}/files?automation=true`,
        formData,
        (loaded, total) => {
          setUploadProgress(
            total ? Math.min(99, Math.round((loaded / total) * 100)) : 0
          );
        }
      );
      setUploadProgress(100);
      didUpload = true;
      currentStage = "parsing";
      setStage("parsing");

      const completed = await waitForAutomatedIngestion({
        fileId: response.file.fileId,
        intervalMs: 1200,
        knowledgeBaseId: selectedKnowledgeBaseId,
        onStage: (nextStage: "parsing" | "chunking" | "embedding" | "complete") => {
          if (nextStage !== "complete") {
            currentStage = nextStage;
          }
          setStage(nextStage);
        },
        request: (path: string, init?: RequestInit) =>
          requestBackend(path, init),
        signal: controller.signal,
        timeoutMessage: t("upload.automationTimeout"),
      });

      setResult({
        chunkCount: completed.parsedDocument.chunkCount,
        fileName: response.file.originalName,
        parsedDocumentId: completed.parsedDocument.parsedDocumentId,
      });
      setStage("complete");
      toast.success(t("upload.automationCompleteToast"));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setFailedAt(currentStage);
      setStage("failed");
      setErrorMessage(
        error instanceof Error ? error.message : t("upload.automationFailed")
      );
      toast.error(t("upload.automationFailed"));
    } finally {
      abortControllerRef.current = null;
      if (didUpload && !controller.signal.aborted) {
        onUploaded();
      }
    }
  };

  const resetWorkflow = () => {
    if (isRunning) {
      return;
    }
    setSelectedFile(null);
    setStage("idle");
    setFailedAt(null);
    setErrorMessage(null);
    setResult(null);
    setUploadProgress(0);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const stageIndex =
    stage === "uploading"
      ? 0
      : stage === "parsing"
        ? 1
        : stage === "chunking"
          ? 2
          : stage === "embedding"
            ? 3
          : stage === "complete"
            ? 4
            : stage === "failed"
              ? failedAt === "uploading"
                ? 0
                : failedAt === "parsing"
                  ? 1
                  : failedAt === "chunking"
                    ? 2
                    : failedAt === "embedding"
                      ? 3
                    : -1
              : -1;
  const connectorWidth =
    stage === "complete"
      ? "100%"
      : `${Math.max(0, stageIndex) * (100 / 3)}%`;
  const steps = [
    { key: "upload", title: t("upload.automationStepUpload") },
    { key: "parse", title: t("upload.automationStepParse") },
    { key: "chunks", title: t("upload.automationStepChunks") },
    { key: "embedding", title: t("upload.automationStepEmbedding") },
  ];

  return (
    <section className="overflow-hidden rounded-2xl border border-border/70 bg-card/50 shadow-[var(--shadow-card)]">
      <div className="flex flex-col gap-4 border-b border-border/70 p-5 sm:flex-row sm:items-end sm:justify-between md:p-7">
        <div>
          <p className="text-muted-foreground text-xs uppercase tracking-[0.16em]">
            {t("upload.destinationLabel")}
          </p>
          <label className="mt-2 block">
            <span className="sr-only">{t("upload.destinationLabel")}</span>
            <select
              aria-label={t("upload.destinationLabel")}
              className="h-10 max-w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition-shadow focus:ring-2 focus:ring-ring"
              disabled={disabled || isRunning}
              onChange={(event) => setSelectedKnowledgeBaseId(event.target.value)}
              value={selectedKnowledgeBaseId}
            >
              {knowledgeBases.map((knowledgeBase) => (
                <option
                  key={knowledgeBase.knowledgeBaseId}
                  value={knowledgeBase.knowledgeBaseId}
                >
                  {knowledgeBase.displayName}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="max-w-xl text-muted-foreground text-xs leading-5">
          {t("upload.automationScope")}
        </p>
      </div>

      <div className="p-5 md:p-7">
        {knowledgeBases.length === 0 ? (
          <div className="mb-6 flex flex-col items-start gap-3 rounded-xl border border-dashed border-border/80 px-5 py-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium text-sm">{t("upload.noKnowledgeBase")}</p>
              <p className="mt-1 text-muted-foreground text-xs leading-5">
                {t("upload.noKnowledgeBaseDescription")}
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/settings/knowledge-bases">
                <PlusIcon />
                {t("upload.createKnowledgeBase")}
              </Link>
            </Button>
          </div>
        ) : null}

        <div className="relative">
          <div
            aria-hidden="true"
            className="absolute left-[12.5%] right-[12.5%] top-4 h-px bg-border"
          >
            <div
              className="h-full bg-primary transition-[width] duration-500"
              style={{ width: connectorWidth }}
            />
          </div>
          <ol
            aria-label={t("upload.automationFlowLabel")}
            aria-live="polite"
            className="grid grid-cols-4 gap-2"
          >
            {steps.map((step, index) => {
              const complete = stage === "complete" || (stageIndex >= 0 && index < stageIndex);
              const current = stageIndex === index && stage !== "complete";
              const failed = stage === "failed" && index === stageIndex;
              return (
                <li className="relative flex min-w-0 flex-col items-center text-center" key={step.key}>
                  <span
                    className={cn(
                      "flex size-8 items-center justify-center rounded-full border text-xs font-semibold transition-colors duration-300",
                      complete
                        ? "border-emerald-600 bg-emerald-600 text-background"
                        : failed
                          ? "border-destructive bg-destructive text-background"
                          : current
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-background text-muted-foreground"
                    )}
                  >
                    {complete ? (
                      <CheckCircle2Icon aria-hidden="true" className="size-4" />
                    ) : failed ? (
                      <AlertTriangleIcon aria-hidden="true" className="size-4" />
                    ) : current && isRunning ? (
                      <LoaderCircleIcon aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <span className="mt-3 max-w-40 text-pretty text-xs font-medium leading-5 sm:text-sm">
                    {step.title}
                  </span>
                  <span className="mt-1 min-h-4 text-[10px] text-muted-foreground sm:text-xs">
                    {complete
                      ? t("upload.automationStepComplete")
                      : failed
                        ? t("upload.automationStepFailed")
                        : current && isRunning
                          ? t("upload.automationStepActive")
                          : t("upload.automationStepWaiting")}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>

        <p aria-live="polite" className="mt-6 text-center text-sm text-muted-foreground" role="status">
          {stage === "complete" && result
            ? t("upload.automationCompleteDescription", { count: result.chunkCount })
            : stage === "uploading"
              ? t("upload.automationUploading")
              : stage === "parsing"
                ? t("upload.automationParsing")
                : stage === "chunking"
                  ? t("upload.automationChunking")
                  : stage === "embedding"
                    ? t("upload.automationEmbedding")
                  : stage === "failed"
                    ? t("upload.automationStopped")
                    : t("upload.automationReady")}
        </p>

        {errorMessage ? (
          <div
            className="mx-auto mt-4 flex max-w-2xl items-start gap-2 rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-left text-destructive text-sm"
            role="alert"
          >
            <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        ) : null}

        {result ? (
          <div className="mx-auto mt-4 flex max-w-2xl items-center gap-3 rounded-lg border border-emerald-600/20 bg-emerald-600/[0.04] px-3 py-3">
            <CheckCircle2Icon className="size-5 shrink-0 text-emerald-600" />
            <div className="min-w-0">
              <p className="truncate font-medium text-sm">{result.fileName}</p>
              <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
                ParsedDocument {result.parsedDocumentId}
              </p>
            </div>
            <Badge className="ml-auto shrink-0" variant="outline">
              {t("upload.automationChunkCount", { count: result.chunkCount })}
            </Badge>
          </div>
        ) : null}

        {selectedFile ? (
          <div className="mx-auto mt-6 flex max-w-2xl items-center gap-3 rounded-xl border border-border/70 bg-background/45 px-3 py-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              {stage === "complete" ? (
                <CheckCircle2Icon className="size-4 text-emerald-600" />
              ) : stage === "failed" ? (
                <AlertTriangleIcon className="size-4 text-destructive" />
              ) : isRunning ? (
                <LoaderCircleIcon className="size-4 animate-spin" />
              ) : (
                <FileIcon className="size-4" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-sm">{selectedFile.name}</p>
              <p className="mt-1 text-muted-foreground text-xs">
                {formatBytes(selectedFile.size)} · {fileKind(selectedFile.name)}
              </p>
              {stage === "uploading" ? (
                <div className="mt-2 flex items-center gap-2">
                  <div
                    aria-label={t("upload.fileProgress", { progress: uploadProgress })}
                    aria-valuemax={100}
                    aria-valuemin={0}
                    aria-valuenow={uploadProgress}
                    className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-border"
                    role="progressbar"
                  >
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-200"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {uploadProgress}%
                  </span>
                </div>
              ) : null}
            </div>
            {!isRunning ? (
              <button
                aria-label={t("upload.removeFile", { name: selectedFile.name })}
                className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={resetWorkflow}
                type="button"
              >
                <XIcon className="size-4" />
              </button>
            ) : null}
          </div>
        ) : null}

        <div
          aria-describedby="automation-dropzone-hint"
          aria-label={t("upload.automationDropTitle")}
          className={cn(
            "group mx-auto mt-6 flex min-h-40 max-w-2xl cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-7 text-center outline-none transition-colors",
            isDragging
              ? "border-foreground bg-muted/70"
              : "border-border/90 bg-background/35 hover:border-foreground/50 hover:bg-muted/30",
            (disabled || isRunning) && "pointer-events-none opacity-60",
            selectedFile && "min-h-28"
          )}
          aria-disabled={disabled || isRunning}
          onClick={() => fileInputRef.current?.click()}
          onDragEnter={(event: DragEvent<HTMLDivElement>) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={(event: DragEvent<HTMLDivElement>) => {
            event.preventDefault();
            setIsDragging(false);
          }}
          onDragOver={(event: DragEvent<HTMLDivElement>) => event.preventDefault()}
          onDrop={(event: DragEvent<HTMLDivElement>) => {
            event.preventDefault();
            setIsDragging(false);
            selectFile(event.dataTransfer.files[0]);
          }}
          onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          role="button"
          tabIndex={disabled || isRunning ? -1 : 0}
        >
          {!selectedFile ? (
            <>
              <UploadCloudIcon className="size-6 text-muted-foreground" strokeWidth={1.5} />
              <p className="mt-3 font-medium text-sm">{t("upload.automationDropTitle")}</p>
              <p className="mt-1 text-muted-foreground text-xs">
                {t("upload.dropDescription")}
              </p>
              <Button className="mt-4" disabled={disabled || isRunning} type="button" variant="outline">
                <FileUpIcon />
                {t("upload.chooseFiles")}
              </Button>
            </>
          ) : (
            <p className="font-medium text-sm">{t("upload.automationChooseAnother")}</p>
          )}
          <p className="mt-3 max-w-sm text-muted-foreground text-xs leading-5" id="automation-dropzone-hint">
            {t("upload.formats")} · {t("upload.maxFileSize")}
          </p>
          <input
            accept={ACCEPT_ATTRIBUTE}
            className="sr-only"
            disabled={disabled || isRunning}
            onChange={(event: ChangeEvent<HTMLInputElement>) => {
              selectFile(event.target.files?.[0]);
              event.target.value = "";
            }}
            ref={fileInputRef}
            type="file"
          />
        </div>
      </div>

      <div className="flex flex-col gap-3 border-t border-border/70 bg-muted/20 px-5 py-4 sm:flex-row sm:items-center sm:justify-between md:px-7">
        <span className="text-muted-foreground text-xs">
          {selectedFile ? t("upload.maxFileSize") : t("upload.automationQueueHint")}
        </span>
        <div className="flex items-center gap-2">
          {stage === "complete" || stage === "failed" ? (
            <Button disabled={isRunning} onClick={resetWorkflow} variant="outline">
              {t("upload.automationAnotherFile")}
            </Button>
          ) : null}
          <Button
            disabled={disabled || !selectedKnowledgeBaseId || !selectedFile || isRunning || stage === "complete"}
            onClick={runAutomation}
          >
            {isRunning ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : stage === "complete" ? (
              <CheckCircle2Icon />
            ) : (
              <FileUpIcon />
            )}
            {isRunning
              ? t("upload.automationRunning")
              : stage === "complete"
                ? t("upload.automationDone")
                : t("upload.automationStart")}
          </Button>
        </div>
      </div>
    </section>
  );
}

function UploadItemRow({
  item,
  onRemove,
  t,
}: {
  item: UploadItem;
  onRemove: (id: string) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const isUploading = item.status === "uploading";
  const statusText =
    item.status === "uploaded"
      ? t("upload.uploaded")
      : item.status === "failed"
        ? t("upload.failed")
        : isUploading
          ? t("upload.uploadingFile")
          : t("upload.ready");

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border px-3 py-3",
        item.status === "failed"
          ? "border-destructive/25 bg-destructive/[0.035]"
          : item.status === "uploaded"
            ? "border-emerald-500/20 bg-emerald-500/[0.035]"
            : "border-border/70 bg-background/45"
      )}
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        {item.status === "uploaded" ? (
          <CheckCircle2Icon className="size-4 text-emerald-600" />
        ) : item.status === "failed" ? (
          <AlertTriangleIcon className="size-4 text-destructive" />
        ) : isUploading ? (
          <LoaderCircleIcon className="size-4 animate-spin" />
        ) : (
          <FileIcon className="size-4" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate font-medium text-sm">{item.file.name}</p>
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
            {fileKind(item.file.name)}
          </span>
        </div>
        <p className="mt-1 truncate text-muted-foreground text-xs">
          {formatBytes(item.file.size)} · {statusText}
        </p>
        {item.errorMessage ? (
          <p className="mt-1 text-destructive text-xs leading-5">{item.errorMessage}</p>
        ) : null}
        {isUploading ? (
          <div className="mt-2 flex items-center gap-2">
            <div
              aria-label={t("upload.fileProgress", { progress: item.progress })}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={item.progress}
              className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-border"
              role="progressbar"
            >
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-200"
                style={{ width: `${item.progress}%` }}
              />
            </div>
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
              {item.progress}%
            </span>
          </div>
        ) : null}
      </div>
      <button
        aria-label={t("upload.removeFile", { name: item.file.name })}
        className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
        disabled={isUploading}
        onClick={() => onRemove(item.id)}
        type="button"
      >
        <XIcon className="size-4" />
      </button>
    </div>
  );
}
