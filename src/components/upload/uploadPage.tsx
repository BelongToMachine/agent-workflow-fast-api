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
import { BackendRequestError, requestBackend } from "@/lib/backend/request";
import { Link } from "@/lib/router";
import { cn } from "@/lib/utils";

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
const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024;

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

type UploadItemStatus = "ready" | "uploading" | "uploaded" | "failed";

type UploadItem = {
  errorMessage?: string;
  id: string;
  file: File;
  status: UploadItemStatus;
};

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
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isLoadingBases, setIsLoadingBases] = useState(true);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
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
            status: "failed",
          });
          continue;
        }

        if (file.size > MAX_FILE_SIZE_BYTES) {
          nextItems.push({
            errorMessage: t("upload.fileTooLarge", { name: file.name }),
            file,
            id,
            status: "failed",
          });
          continue;
        }

        nextItems.push({ file, id, status: "ready" });
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
            ? { ...currentItem, status: "uploading", errorMessage: undefined }
            : currentItem
        )
      );

      try {
        const formData = new FormData();
        formData.append("file", item.file);
        await requestBackend<{ file: KnowledgeFile }>(
          `/api/knowledge-bases/${encodeURIComponent(selectedKnowledgeBaseId)}/files`,
          { body: formData, method: "POST" }
        );
        uploadedCount += 1;
        setItems((current) =>
          current.map((currentItem) =>
            currentItem.id === item.id
              ? { ...currentItem, status: "uploaded" }
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

  if (isLoadingBases) {
    return (
      <main className="min-h-full bg-background px-4 py-8 md:px-8 md:py-10">
        <div className="mx-auto max-w-6xl animate-pulse space-y-6">
          <div className="h-32 rounded-2xl bg-muted/50" />
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
            <div className="h-[28rem] rounded-2xl bg-muted/50" />
            <div className="h-[28rem] rounded-2xl bg-muted/50" />
          </div>
        </div>
      </main>
    );
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
              {t("upload.description")}
            </p>
          </div>
          <div className="flex items-center gap-3 text-muted-foreground text-xs">
            <span className="font-mono text-foreground">01</span>
            <span aria-hidden="true" className="h-px w-8 bg-border" />
            <span>{t("upload.stepLabel")}</span>
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

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <section className="min-w-0 rounded-2xl border border-border/70 bg-card/50 shadow-[var(--shadow-card)]">
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
                <div className="text-muted-foreground text-xs">
                  {items.length > 0 ? (
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

          <aside className="flex flex-col gap-5">
            <section className="rounded-2xl border border-border/70 bg-card/50 p-5 shadow-[var(--shadow-card)] md:p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-mono text-muted-foreground text-xs">01 / 03</p>
                  <h2 className="mt-4 font-medium text-base tracking-tight">{t("upload.sideTitle")}</h2>
                </div>
                <span className="flex size-8 items-center justify-center rounded-full bg-muted text-muted-foreground">
                  <DatabaseIcon className="size-4" />
                </span>
              </div>
              <p className="mt-3 text-muted-foreground text-sm leading-6">{t("upload.sideDescription")}</p>
              <div className="mt-5 space-y-3 border-t border-border/70 pt-5">
                <SideNote label={t("upload.sideFormats")} value="XLSX · CSV · JSON · MD · TXT · PDF · PPT" />
                <SideNote label={t("upload.sideLimit")} value="25 MB / file" />
                <SideNote label={t("upload.sideNext")} value={t("upload.sideNextValue")} />
              </div>
            </section>

            <section className="rounded-2xl border border-border/70 bg-primary/[0.035] p-5 md:p-6">
              <LockKeyholeIcon className="size-4 text-muted-foreground" />
              <h2 className="mt-4 font-medium text-base tracking-tight">{t("upload.privacyTitle")}</h2>
              <p className="mt-2 text-muted-foreground text-sm leading-6">{t("upload.privacyDescription")}</p>
            </section>
          </aside>
        </div>
      </div>
    </main>
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

function SideNote({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{value}</span>
    </div>
  );
}
