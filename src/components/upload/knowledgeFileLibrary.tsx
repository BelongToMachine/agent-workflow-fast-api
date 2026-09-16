"use client";

import {
  CheckCircle2Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DatabaseIcon,
  EyeIcon,
  FileArchiveIcon,
  FileClockIcon,
  FileTextIcon,
  Layers3Icon,
  LoaderCircleIcon,
  RefreshCwIcon,
  ScanTextIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InlineLoadingState } from "@/components/ui/loadingState";
import { BackendRequestError, requestBackend } from "@/lib/backend/request";
import { cn } from "@/lib/utils";

type KnowledgeFile = {
  byteSize: number;
  createdAt: string;
  errorMessage: string | null;
  fileHash: string;
  fileId: string;
  knowledgeBaseId: string;
  mimeType: string;
  originalName: string;
  status: string;
  storageProvider: string;
  updatedAt: string;
};

type KnowledgeFileListResponse = {
  files: KnowledgeFile[];
};

type ParsedBlock = {
  blockId: string;
  data?: unknown;
  extractionMethod: string;
  kind: string;
  locator: Record<string, string | number>;
  text: string;
};

type ParsedDocument = {
  blocks: ParsedBlock[];
  contentType: string;
  fileHash: string;
  fileId: string | null;
  mimeType: string;
  nextCursor: number | null;
  originalName: string;
  parser: string;
  parserVersion: string;
  schemaVersion: string;
  totalBlocks: number | null;
  truncated: boolean;
  warnings: string[];
};

type ParsedDocumentResponse = {
  chunkCount: number;
  chunkErrorMessage: string | null;
  chunkStatus: string;
  createdAt: string;
  parsedDocument: ParsedDocument;
  parsedDocumentId: string;
  updatedAt: string;
};

type Props = {
  disabled?: boolean;
  knowledgeBaseId: string;
  refreshKey?: number;
};

const PARSED_DOCUMENT_PAGE_SIZE = 30;

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

function isProcessing(status: string) {
  return status === "processing";
}

function chunkStatusVariant(
  status: string
): "default" | "destructive" | "outline" {
  if (status === "failed") {
    return "destructive";
  }
  if (status === "ready") {
    return "default";
  }
  return "outline";
}

export function KnowledgeFileLibrary({
  disabled = false,
  knowledgeBaseId,
  refreshKey = 0,
}: Props) {
  const { i18n, t } = useTranslation();
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(
    () => new Set()
  );
  const [isLoading, setIsLoading] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [isGeneratingChunks, setIsGeneratingChunks] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedParsedFileId, setSelectedParsedFileId] = useState<string | null>(
    null
  );
  const [parsedDocument, setParsedDocument] =
    useState<ParsedDocumentResponse | null>(null);
  const [parsedDocumentOffset, setParsedDocumentOffset] = useState(0);
  const [isLoadingParsedDocument, setIsLoadingParsedDocument] = useState(false);
  const [parsedDocumentError, setParsedDocumentError] = useState<string | null>(
    null
  );

  const loadFiles = useCallback(async () => {
    if (!knowledgeBaseId) {
      setFiles([]);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const data = await requestBackend<KnowledgeFileListResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files`
      );
      setFiles(data.files);
    } catch (loadError) {
      if (loadError instanceof BackendRequestError && loadError.status === 409) {
        setError(t("settings.ingestionDisabled"));
      } else {
        setError(
          loadError instanceof Error
            ? loadError.message
            : t("settings.unableToLoadKnowledgeFiles")
        );
      }
      setFiles([]);
    } finally {
      setIsLoading(false);
    }
  }, [knowledgeBaseId, t]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles, refreshKey]);

  useEffect(() => {
    const availableIds = new Set(files.map(({ fileId }) => fileId));
    setSelectedFileIds((current) => {
      const next = new Set(
        [...current].filter((fileId) => availableIds.has(fileId))
      );
      return next.size === current.size ? current : next;
    });
  }, [files]);

  useEffect(() => {
    if (!files.some(({ status }) => isProcessing(status))) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadFiles();
    }, 1500);
    return () => window.clearInterval(intervalId);
  }, [files, loadFiles]);

  const selectableFiles = useMemo(
    () => files.filter(({ status }) => !isProcessing(status)),
    [files]
  );
  const selectedFiles = useMemo(
    () => files.filter(({ fileId }) => selectedFileIds.has(fileId)),
    [files, selectedFileIds]
  );
  const selectedChunkableFiles = useMemo(
    () => selectedFiles.filter(({ status }) => status === "ready"),
    [selectedFiles]
  );

  const toggleFile = useCallback((fileId: string) => {
    setSelectedFileIds((current) => {
      const next = new Set(current);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedFileIds((current) => {
      if (current.size === selectableFiles.length) {
        return new Set();
      }
      return new Set(selectableFiles.map(({ fileId }) => fileId));
    });
  }, [selectableFiles]);

  const loadParsedDocument = useCallback(
    async (fileId: string, offset: number) => {
      setSelectedParsedFileId(fileId);
      setParsedDocumentOffset(offset);
      setIsLoadingParsedDocument(true);
      setParsedDocumentError(null);
      try {
        const data = await requestBackend<ParsedDocumentResponse>(
          `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(fileId)}/parsed-document?offset=${offset}&limit=${PARSED_DOCUMENT_PAGE_SIZE}`
        );
        setParsedDocument(data);
      } catch (documentError) {
        setParsedDocument(null);
        setParsedDocumentError(
          documentError instanceof Error
            ? documentError.message
            : t("settings.unableToLoadParsedDocument")
        );
      } finally {
        setIsLoadingParsedDocument(false);
      }
    },
    [knowledgeBaseId, t]
  );

  useEffect(() => {
    if (!selectedParsedFileId || parsedDocument?.chunkStatus !== "processing") {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadParsedDocument(selectedParsedFileId, parsedDocumentOffset);
    }, 1500);
    return () => window.clearInterval(intervalId);
  }, [
    loadParsedDocument,
    parsedDocument?.chunkStatus,
    parsedDocumentOffset,
    selectedParsedFileId,
  ]);

  const parseSelectedFiles = useCallback(async () => {
    if (isParsing || disabled || selectedFileIds.size === 0) {
      return;
    }

    setIsParsing(true);
    setError(null);
    let startedCount = 0;
    let failedCount = 0;

    for (const fileId of selectedFileIds) {
      try {
        const data = await requestBackend<{ file: KnowledgeFile }>(
          `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(fileId)}/parse`,
          { method: "POST" }
        );
        setFiles((current) =>
          current.map((file) =>
            file.fileId === fileId ? { ...file, ...data.file } : file
          )
        );
        startedCount += 1;
      } catch (parseError) {
        failedCount += 1;
        setError(
          parseError instanceof Error
            ? parseError.message
            : t("settings.parseKnowledgeFileFailed")
        );
      }
    }

    setSelectedFileIds(new Set());
    setIsParsing(false);
    await loadFiles();
    if (failedCount === 0) {
      toast.success(
        t("settings.parseKnowledgeFilesStarted", { count: startedCount })
      );
    } else if (startedCount > 0) {
      toast.warning(
        t("settings.parseKnowledgeFilesPartial", { count: startedCount })
      );
    } else {
      toast.error(t("settings.parseKnowledgeFileFailed"));
    }
  }, [disabled, isParsing, knowledgeBaseId, loadFiles, selectedFileIds, t]);

  const generateChunks = useCallback(async () => {
    if (
      isGeneratingChunks ||
      disabled ||
      selectedChunkableFiles.length === 0
    ) {
      return;
    }

    setIsGeneratingChunks(true);
    setError(null);
    let startedCount = 0;
    let failedCount = 0;
    for (const file of selectedChunkableFiles) {
      try {
        await requestBackend<ParsedDocumentResponse>(
          `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(file.fileId)}/chunks`,
          { method: "POST" }
        );
        startedCount += 1;
      } catch (chunkError) {
        failedCount += 1;
        setError(
          chunkError instanceof Error
            ? chunkError.message
            : t("settings.generateKnowledgeChunksFailed")
        );
      }
    }

    setSelectedFileIds(new Set());
    setIsGeneratingChunks(false);
    if (
      selectedParsedFileId &&
      selectedChunkableFiles.some(
        ({ fileId }) => fileId === selectedParsedFileId
      )
    ) {
      await loadParsedDocument(selectedParsedFileId, parsedDocumentOffset);
    }
    if (failedCount === 0) {
      toast.success(
        t("settings.generateKnowledgeChunksStarted", { count: startedCount })
      );
    } else if (startedCount > 0) {
      toast.warning(
        t("settings.generateKnowledgeChunksPartial", { count: startedCount })
      );
    } else {
      toast.error(t("settings.generateKnowledgeChunksFailed"));
    }
  }, [
    disabled,
    isGeneratingChunks,
    knowledgeBaseId,
    loadParsedDocument,
    parsedDocumentOffset,
    selectedChunkableFiles,
    selectedParsedFileId,
    t,
  ]);

  const allSelectableSelected =
    selectableFiles.length > 0 && selectedFileIds.size === selectableFiles.length;

  return (
    <section className="mt-6 rounded-2xl border border-border/70 bg-card/50 shadow-[var(--shadow-card)]">
      <div className="flex flex-col gap-4 border-b border-border/70 p-5 md:flex-row md:items-start md:justify-between md:p-7">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <FileArchiveIcon className="size-5" />
          </span>
          <div>
            <p className="text-muted-foreground text-xs uppercase tracking-[0.14em]">
              {t("settings.knowledgeFilesStoredTitle")}
            </p>
            <h2 className="mt-2 font-semibold text-xl tracking-tight">
              {t("settings.knowledgeFilesStoredHeading")}
            </h2>
            <p className="mt-1 max-w-2xl text-muted-foreground text-sm leading-6">
              {t("settings.knowledgeFilesStoredDescription")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 self-start">
          <Badge className="gap-1.5 px-3 py-1.5" variant="outline">
            <FileTextIcon className="size-3.5" />
            {t("settings.fileCount", {
              count: files.length,
              label: files.length === 1 ? t("common.file") : t("common.files"),
            })}
          </Badge>
          <Button
            aria-label={t("settings.refreshKnowledgeFiles")}
            disabled={isLoading || isParsing || isGeneratingChunks}
            onClick={() => void loadFiles()}
            size="icon-sm"
            variant="outline"
          >
            <RefreshCwIcon className={cn(isLoading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {error ? (
        <div
          aria-live="polite"
          className="border-b border-destructive/20 bg-destructive/5 px-5 py-3 text-destructive text-sm md:px-7"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <div className="p-5 md:p-7">
        {isLoading ? (
          <InlineLoadingState message={t("common.loading")} />
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
          <>
            <div className="mb-4 flex flex-col gap-3 border-b border-border/70 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <label className="flex items-center gap-2 text-muted-foreground text-sm">
                <input
                  checked={allSelectableSelected}
                  disabled={
                    disabled ||
                    isParsing ||
                    isGeneratingChunks ||
                    selectableFiles.length === 0
                  }
                  onChange={toggleAll}
                  type="checkbox"
                />
                {t("settings.selectFilesToParse", { count: selectedFileIds.size })}
              </label>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={
                    disabled ||
                    isParsing ||
                    isGeneratingChunks ||
                    selectedFileIds.size === 0
                  }
                  onClick={() => void parseSelectedFiles()}
                  size="sm"
                >
                  {isParsing ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <ScanTextIcon />
                  )}
                  {isParsing
                    ? t("settings.parsingKnowledgeFiles")
                    : t("settings.parseSelectedFiles")}
                </Button>
                <Button
                  disabled={
                    disabled ||
                    isParsing ||
                    isGeneratingChunks ||
                    selectedChunkableFiles.length === 0
                  }
                  onClick={() => void generateChunks()}
                  size="sm"
                  variant="outline"
                >
                  {isGeneratingChunks ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <Layers3Icon />
                  )}
                  {isGeneratingChunks
                    ? t("settings.generatingKnowledgeChunks")
                    : t("settings.generateKnowledgeChunks")}
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              {files.map((file) => (
                <StoredFileRow
                  file={file}
                  i18nLanguage={i18n.language}
                  key={file.fileId}
                  onToggle={toggleFile}
                  onViewParsedDocument={(fileId) =>
                    void loadParsedDocument(fileId, 0)
                  }
                  selected={selectedFileIds.has(file.fileId)}
                  t={t}
                  viewing={selectedParsedFileId === file.fileId}
                />
              ))}
            </div>
          </>
        )}

        {selectedParsedFileId ? (
          <ParsedDocumentPanel
            error={parsedDocumentError}
            hasPrevious={parsedDocumentOffset > 0}
            i18nLanguage={i18n.language}
            isLoading={isLoadingParsedDocument}
            onNext={() => {
              if (parsedDocument?.parsedDocument.nextCursor !== null) {
                void loadParsedDocument(
                  selectedParsedFileId,
                  parsedDocument.parsedDocument.nextCursor
                );
              }
            }}
            onPrevious={() =>
              void loadParsedDocument(
                selectedParsedFileId,
                Math.max(0, parsedDocumentOffset - PARSED_DOCUMENT_PAGE_SIZE)
              )
            }
            parsedDocument={parsedDocument}
            t={t}
          />
        ) : null}
      </div>
    </section>
  );
}

function StoredFileRow({
  file,
  i18nLanguage,
  onToggle,
  onViewParsedDocument,
  selected,
  t,
  viewing,
}: {
  file: KnowledgeFile;
  i18nLanguage: string;
  onToggle: (fileId: string) => void;
  onViewParsedDocument: (fileId: string) => void;
  selected: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
  viewing: boolean;
}) {
  const processing = isProcessing(file.status);
  const ready = file.status === "ready";
  const statusText = ready
    ? t("settings.ready")
    : file.status === "pending"
      ? t("settings.awaitingParse")
      : processing
        ? t("settings.processing")
        : file.status === "failed"
          ? t("settings.failed")
          : t("settings.queued");

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border border-border/70 bg-background/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between",
        selected && "border-primary/50 bg-primary/[0.04]",
        viewing && "ring-1 ring-primary/30",
        processing && "opacity-75"
      )}
    >
      <label className="flex min-w-0 items-start gap-3">
        <input
          aria-label={t("settings.selectFileToParse", { name: file.originalName })}
          checked={selected}
          disabled={processing}
          onChange={() => onToggle(file.fileId)}
          type="checkbox"
        />
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          {ready ? (
            <CheckCircle2Icon className="size-4 text-emerald-600" />
          ) : processing ? (
            <FileClockIcon className="size-4" />
          ) : (
            <FileTextIcon className="size-4" />
          )}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium text-sm">{file.originalName}</span>
          <span className="mt-1 block text-muted-foreground text-xs">
            {formatBytes(file.byteSize)} · {file.storageProvider.toUpperCase()} · {t("common.uploaded")} {formatDate(file.createdAt, i18nLanguage, t("common.unknownDate"))}
          </span>
          {file.errorMessage ? (
            <span className="mt-1 block text-destructive text-xs">{file.errorMessage}</span>
          ) : null}
        </span>
      </label>
      <div className="flex items-center justify-end gap-2 self-end sm:self-auto">
        {ready ? (
          <Button
            onClick={() => onViewParsedDocument(file.fileId)}
            size="sm"
            variant={viewing ? "secondary" : "ghost"}
          >
            <EyeIcon />
            {t("settings.viewParsedDocument")}
          </Button>
        ) : null}
        <Badge variant={file.status === "failed" ? "destructive" : "outline"}>
          {processing ? <LoaderCircleIcon className="animate-spin" /> : null}
          {statusText}
        </Badge>
      </div>
    </div>
  );
}

function ParsedDocumentPanel({
  error,
  hasPrevious,
  i18nLanguage,
  isLoading,
  onNext,
  onPrevious,
  parsedDocument,
  t,
}: {
  error: string | null;
  hasPrevious: boolean;
  i18nLanguage: string;
  isLoading: boolean;
  onNext: () => void;
  onPrevious: () => void;
  parsedDocument: ParsedDocumentResponse | null;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  return (
    <div className="mt-6 rounded-2xl border border-primary/20 bg-primary/[0.025]">
      <div className="flex flex-col gap-3 border-b border-border/70 p-5 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <DatabaseIcon className="size-5" />
          </span>
          <div>
            <p className="text-muted-foreground text-xs uppercase tracking-[0.14em]">
              {t("settings.parsedDocumentTitle")}
            </p>
            <h3 className="mt-1 font-semibold text-lg tracking-tight">
              {parsedDocument?.parsedDocument.originalName ?? t("common.loading")}
            </h3>
            <p className="mt-1 text-muted-foreground text-sm">
              {t("settings.parsedDocumentDescription")}
            </p>
          </div>
        </div>
        {parsedDocument ? (
          <div className="flex flex-wrap gap-2">
            <Badge variant={chunkStatusVariant(parsedDocument.chunkStatus)}>
              {t(`settings.chunkStatus.${parsedDocument.chunkStatus}`)}
            </Badge>
            <Badge variant="outline">
              {t("settings.parsedDocumentBlockCount", {
                count:
                  parsedDocument.parsedDocument.totalBlocks ??
                  parsedDocument.parsedDocument.blocks.length,
              })}
            </Badge>
          </div>
        ) : null}
      </div>

      {error ? (
        <div
          className="m-5 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-destructive text-sm"
          role="alert"
        >
          {error}
        </div>
      ) : isLoading ? (
        <div className="p-5">
          <InlineLoadingState message={t("settings.loadingParsedDocument")} />
        </div>
      ) : parsedDocument ? (
        <>
          <div className="grid gap-3 border-b border-border/70 p-5 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Metadata
              label={t("settings.parser")}
              value={`${parsedDocument.parsedDocument.parser} · ${parsedDocument.parsedDocument.parserVersion}`}
            />
            <Metadata
              label={t("settings.parsedDocumentSchema")}
              value={parsedDocument.parsedDocument.schemaVersion}
            />
            <Metadata
              label={t("settings.parsedDocumentContentType")}
              value={parsedDocument.parsedDocument.contentType}
            />
            <Metadata
              label={t("settings.knowledgeChunks")}
              value={String(parsedDocument.chunkCount)}
            />
          </div>
          {parsedDocument.parsedDocument.warnings.length > 0 ? (
            <div className="border-b border-amber-500/20 bg-amber-500/[0.06] px-5 py-3 text-amber-800 text-sm dark:text-amber-200">
              {parsedDocument.parsedDocument.warnings.join(" ")}
            </div>
          ) : null}
          {parsedDocument.chunkErrorMessage ? (
            <div className="border-b border-destructive/20 bg-destructive/5 px-5 py-3 text-destructive text-sm">
              {parsedDocument.chunkErrorMessage}
            </div>
          ) : null}
          <div className="space-y-3 p-5">
            {parsedDocument.parsedDocument.blocks.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border/80 px-4 py-8 text-center text-muted-foreground text-sm">
                {t("settings.noParsedBlocks")}
              </p>
            ) : (
              parsedDocument.parsedDocument.blocks.map((block, index) => (
                <article
                  className="rounded-xl border border-border/70 bg-background/70 p-4"
                  key={block.blockId}
                >
                  <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
                    <Badge variant="outline">{block.kind}</Badge>
                    <span>{block.extractionMethod}</span>
                    <span>#{index + 1}</span>
                    <span>{formatLocator(block.locator)}</span>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                    {block.text}
                  </p>
                  {block.data !== undefined && block.data !== null ? (
                    <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-muted/70 p-3 text-xs leading-5">
                      {JSON.stringify(block.data, null, 2)}
                    </pre>
                  ) : null}
                </article>
              ))
            )}
          </div>
          <div className="flex flex-col gap-3 border-t border-border/70 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-muted-foreground text-xs">
              {t("settings.parsedDocumentUpdatedAt", {
                date: formatDate(
                  parsedDocument.updatedAt,
                  i18nLanguage,
                  t("common.unknownDate")
                ),
              })}
            </span>
            <div className="flex gap-2 self-end">
              <Button
                disabled={!hasPrevious}
                onClick={onPrevious}
                size="sm"
                variant="outline"
              >
                <ChevronLeftIcon />
                {t("settings.previousParsedBlocks")}
              </Button>
              <Button
                disabled={parsedDocument.parsedDocument.nextCursor === null}
                onClick={onNext}
                size="sm"
                variant="outline"
              >
                {t("settings.nextParsedBlocks")}
                <ChevronRightIcon />
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function Metadata({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
        {label}
      </p>
      <p className="mt-1 truncate font-medium">{value}</p>
    </div>
  );
}

function formatLocator(locator: Record<string, string | number>) {
  return Object.entries(locator)
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
}
