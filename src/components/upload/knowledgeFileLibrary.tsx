"use client";

import {
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DatabaseIcon,
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
import {
  getKnowledgeChunkActionLabelKey,
  getKnowledgeChunkSelectorKey,
} from "@/lib/knowledgeChunkAction";
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

type ParsedDocumentListItem = {
  chunkCount: number;
  chunkErrorMessage: string | null;
  chunkStatus: string;
  createdAt: string;
  fileByteSize: number;
  fileHash: string;
  fileId: string;
  fileMimeType: string;
  fileName: string;
  fileStatus: string;
  parsedDocument: ParsedDocument;
  parsedDocumentId: string;
  updatedAt: string;
};

type ParsedDocumentListResponse = {
  items: ParsedDocumentListItem[];
  limit: number;
  nextOffset: number | null;
  offset: number;
  total: number;
};

type ParsedDocumentTaskResponse = {
  chunkCount: number;
  chunkErrorMessage: string | null;
  chunkStatus: string;
  createdAt: string;
  parsedDocument: ParsedDocument;
  parsedDocumentId: string;
  updatedAt: string;
};

type KnowledgeChunk = {
  chunkId: string;
  chunkIndex: number;
  content: string;
  embeddingModel: string | null;
  isEmbedded: boolean;
};

type KnowledgeChunkPage = {
  items: KnowledgeChunk[];
  limit: number;
  nextOffset: number | null;
  offset: number;
  total: number;
};

type KnowledgeChunkEmbeddingResponse = {
  dimensions: number;
  embeddedCount: number;
  embeddingModel: string;
};

type Props = {
  disabled?: boolean;
  knowledgeBaseId: string;
  refreshKey?: number;
};

const PARSED_DOCUMENT_PAGE_SIZE = 20;
const PARSED_BLOCK_PAGE_SIZE = 30;
const KNOWLEDGE_CHUNK_PAGE_SIZE = 20;

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

function formatLocator(locator: Record<string, string | number>) {
  return Object.entries(locator)
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
}

function shortHash(value: string) {
  return value.length > 20 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
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
  const [parsedDocuments, setParsedDocuments] =
    useState<ParsedDocumentListResponse | null>(null);
  const [isLoadingParsedDocuments, setIsLoadingParsedDocuments] = useState(true);
  const [parsedDocumentsError, setParsedDocumentsError] = useState<string | null>(
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

  const loadParsedDocuments = useCallback(
    async (offset = 0) => {
      if (!knowledgeBaseId) {
        setParsedDocuments(null);
        return;
      }

      setIsLoadingParsedDocuments(true);
      setParsedDocumentsError(null);
      try {
        const data = await requestBackend<ParsedDocumentListResponse>(
          `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/parsed-documents?offset=${offset}&limit=${PARSED_DOCUMENT_PAGE_SIZE}&block_offset=0&block_limit=${PARSED_BLOCK_PAGE_SIZE}`
        );
        setParsedDocuments(data);
      } catch (loadError) {
        setParsedDocuments(null);
        if (loadError instanceof BackendRequestError && loadError.status === 409) {
          setParsedDocumentsError(t("settings.ingestionDisabled"));
        } else {
          setParsedDocumentsError(
            loadError instanceof Error
              ? loadError.message
              : t("settings.unableToLoadParsedDocuments")
          );
        }
      } finally {
        setIsLoadingParsedDocuments(false);
      }
    },
    [knowledgeBaseId, t]
  );

  useEffect(() => {
    void loadFiles();
  }, [loadFiles, refreshKey]);

  useEffect(() => {
    setParsedDocuments(null);
    setParsedDocumentsError(null);
    void loadParsedDocuments(0);
  }, [loadParsedDocuments]);

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
      void loadParsedDocuments(parsedDocuments?.offset ?? 0);
    }, 1500);
    return () => window.clearInterval(intervalId);
  }, [files, loadFiles, loadParsedDocuments, parsedDocuments?.offset]);

  useEffect(() => {
    if (!parsedDocuments?.items.some(({ chunkStatus }) => isProcessing(chunkStatus))) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadParsedDocuments(parsedDocuments.offset);
    }, 1500);
    return () => window.clearInterval(intervalId);
  }, [loadParsedDocuments, parsedDocuments]);

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
    await loadParsedDocuments(parsedDocuments?.offset ?? 0);
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
  }, [
    disabled,
    isParsing,
    knowledgeBaseId,
    loadFiles,
    loadParsedDocuments,
    parsedDocuments?.offset,
    selectedFileIds,
    t,
  ]);

  const generateChunksForFiles = useCallback(
    async (fileIds: string[]) => {
      if (isGeneratingChunks || disabled || fileIds.length === 0) {
        return;
      }

      const uniqueFileIds = [...new Set(fileIds)];
      setIsGeneratingChunks(true);
      setError(null);
      let startedCount = 0;
      let failedCount = 0;
      for (const fileId of uniqueFileIds) {
        try {
          await requestBackend<ParsedDocumentTaskResponse>(
            `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(fileId)}/chunks`,
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
      await loadFiles();
      await loadParsedDocuments(parsedDocuments?.offset ?? 0);
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
    },
    [
      disabled,
      isGeneratingChunks,
      knowledgeBaseId,
      loadFiles,
      loadParsedDocuments,
      parsedDocuments?.offset,
      t,
    ]
  );

  const allSelectableSelected =
    selectableFiles.length > 0 && selectedFileIds.size === selectableFiles.length;

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-border/70 bg-card/50 shadow-[var(--shadow-card)]">
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
        <div className="flex flex-wrap items-center gap-2 self-start">
          <Badge className="gap-1.5 px-3 py-1.5" variant="outline">
            <FileTextIcon className="size-3.5" />
            {t("settings.fileCount", {
              count: files.length,
              label: files.length === 1 ? t("common.file") : t("common.files"),
            })}
          </Badge>
          <Button
            disabled={isLoading || isParsing || isGeneratingChunks}
            onClick={() => void loadFiles()}
            size="icon-sm"
            variant="outline"
            aria-label={t("settings.refreshKnowledgeFiles")}
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
                  onClick={() =>
                    void generateChunksForFiles(
                      selectedChunkableFiles.map(({ fileId }) => fileId)
                    )
                  }
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
                  selected={selectedFileIds.has(file.fileId)}
                  t={t}
                />
              ))}
            </div>
          </>
        )}

      </div>
      </section>
      <ParsedDocumentLibrary
        data={parsedDocuments}
        disabled={disabled}
        error={parsedDocumentsError}
        i18nLanguage={i18n.language}
        isLoading={isLoadingParsedDocuments}
        knowledgeBaseId={knowledgeBaseId}
        onGenerateChunks={(fileId) =>
          void generateChunksForFiles([fileId])
        }
        onNext={() => {
          if (parsedDocuments?.nextOffset !== null && parsedDocuments) {
            void loadParsedDocuments(parsedDocuments.nextOffset);
          }
        }}
        onPrevious={() => {
          if (parsedDocuments && parsedDocuments.offset > 0) {
            void loadParsedDocuments(
              Math.max(0, parsedDocuments.offset - parsedDocuments.limit)
            );
          }
        }}
        t={t}
        isGeneratingChunks={isGeneratingChunks}
      />
    </div>
  );
}

function StoredFileRow({
  file,
  i18nLanguage,
  onToggle,
  selected,
  t,
}: {
  file: KnowledgeFile;
  i18nLanguage: string;
  onToggle: (fileId: string) => void;
  selected: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
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
      <Badge variant={file.status === "failed" ? "destructive" : "outline"}>
        {processing ? <LoaderCircleIcon className="animate-spin" /> : null}
        {statusText}
      </Badge>
    </div>
  );
}

function ParsedDocumentLibrary({
  data,
  disabled,
  error,
  i18nLanguage,
  isLoading,
  isGeneratingChunks,
  knowledgeBaseId,
  onGenerateChunks,
  onNext,
  onPrevious,
  t,
}: {
  data: ParsedDocumentListResponse | null;
  disabled: boolean;
  error: string | null;
  i18nLanguage: string;
  isLoading: boolean;
  isGeneratingChunks: boolean;
  knowledgeBaseId: string;
  onGenerateChunks: (fileId: string) => void;
  onNext: () => void;
  onPrevious: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  return (
    <section className="rounded-2xl border border-primary/20 bg-primary/[0.025]">
      <div className="flex flex-col gap-3 border-b border-border/70 p-5 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <DatabaseIcon className="size-5" />
          </span>
          <div>
            <p className="text-muted-foreground text-xs uppercase tracking-[0.14em]">
              {t("settings.parsedDocumentsTitle")}
            </p>
            <h2 className="mt-1 font-semibold text-lg tracking-tight">
              {t("settings.parsedDocumentsHeading")}
            </h2>
            <p className="mt-1 text-muted-foreground text-sm">
              {t("settings.parsedDocumentsDescription")}
            </p>
          </div>
        </div>
        {data ? (
          <Badge variant="outline">
            {t("settings.parsedDocumentsCount", { count: data.total })}
          </Badge>
        ) : null}
      </div>

      {error ? (
        <div
          className="m-5 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-destructive text-sm"
          role="alert"
        >
          {error}
        </div>
      ) : isLoading && !data ? (
        <div className="p-5">
          <InlineLoadingState message={t("settings.loadingParsedDocuments")} />
        </div>
      ) : !data || data.items.length === 0 ? (
        <p className="m-5 rounded-xl border border-dashed border-border/80 px-4 py-10 text-center text-muted-foreground text-sm">
          {t("settings.noParsedDocuments")}
        </p>
      ) : (
        <>
          <div className="space-y-4 p-5">
            {data.items.map((item) => (
              <ParsedDocumentCard
                disabled={disabled}
                i18nLanguage={i18nLanguage}
                isGeneratingChunks={isGeneratingChunks}
                item={item}
                knowledgeBaseId={knowledgeBaseId}
                key={item.parsedDocumentId}
                onGenerateChunks={onGenerateChunks}
                t={t}
              />
            ))}
          </div>
          <div className="flex flex-col gap-3 border-t border-border/70 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-muted-foreground text-xs">
              {t("settings.parsedDocumentsPage", {
                from: data.offset + 1,
                to: Math.min(data.offset + data.items.length, data.total),
                total: data.total,
              })}
            </span>
            <div className="flex gap-2 self-end">
              <Button
                disabled={data.offset === 0 || isLoading}
                onClick={onPrevious}
                size="sm"
                variant="outline"
              >
                <ChevronLeftIcon />
                {t("settings.previousParsedDocuments")}
              </Button>
              <Button
                disabled={data.nextOffset === null || isLoading}
                onClick={onNext}
                size="sm"
                variant="outline"
              >
                {t("settings.nextParsedDocuments")}
                <ChevronRightIcon />
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function ParsedDocumentCard({
  disabled,
  i18nLanguage,
  isGeneratingChunks,
  item,
  knowledgeBaseId,
  onGenerateChunks,
  t,
}: {
  disabled: boolean;
  i18nLanguage: string;
  isGeneratingChunks: boolean;
  item: ParsedDocumentListItem;
  knowledgeBaseId: string;
  onGenerateChunks: (fileId: string) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const document = item.parsedDocument;
  const [isExpanded, setIsExpanded] = useState(false);
  const detailsId = `parsed-document-details-${item.parsedDocumentId}`;

  return (
    <article className="overflow-hidden rounded-xl border border-border/70 bg-background/60">
      <div className="flex flex-col gap-3 border-b border-border/70 p-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <h4 className="truncate font-semibold text-base">{item.fileName}</h4>
          <p className="mt-1 text-muted-foreground text-xs">
            {formatBytes(item.fileByteSize)} · {item.fileMimeType} · {t("common.uploaded")} {formatDate(item.createdAt, i18nLanguage, t("common.unknownDate"))}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={item.fileStatus === "failed" ? "destructive" : "outline"}>
            {item.fileStatus}
          </Badge>
          <Badge variant={chunkStatusVariant(item.chunkStatus)}>
            {t(`settings.chunkStatus.${item.chunkStatus}`)}
          </Badge>
          <Button
            aria-controls={detailsId}
            aria-expanded={isExpanded}
            onClick={() => setIsExpanded((current) => !current)}
            size="sm"
            variant="ghost"
          >
            <ChevronDownIcon
              className={cn(
                "transition-transform duration-200",
                isExpanded && "rotate-180"
              )}
            />
            {t(
              isExpanded
                ? "settings.collapseParsedDocument"
                : "settings.expandParsedDocument"
            )}
          </Button>
        </div>
      </div>

      {isExpanded ? (
        <div id={detailsId}>
          <div className="grid gap-3 border-b border-border/70 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Metadata
              label={t("settings.parser")}
              value={`${document.parser} · ${document.parserVersion}`}
            />
            <Metadata
              label={t("settings.parsedDocumentSchema")}
              value={document.schemaVersion}
            />
            <Metadata
              label={t("settings.parsedDocumentContentType")}
              value={document.contentType}
            />
            <Metadata
              label={t("settings.knowledgeChunks")}
              value={String(item.chunkCount)}
            />
          </div>

          <div className="border-b border-border/70 px-4 py-3 text-xs">
            <p className="text-muted-foreground">
              {t("settings.parsedDocumentFileHash")}: {shortHash(item.fileHash)}
            </p>
            <p className="mt-1 text-muted-foreground">
              {t("settings.parsedDocumentId")}: {shortHash(item.parsedDocumentId)}
            </p>
          </div>

          {document.warnings.length > 0 ? (
            <div className="border-b border-amber-500/20 bg-amber-500/[0.06] px-4 py-3 text-amber-800 text-sm dark:text-amber-200">
              {document.warnings.join(" ")}
            </div>
          ) : null}
          {item.chunkErrorMessage ? (
            <div className="border-b border-destructive/20 bg-destructive/5 px-4 py-3 text-destructive text-sm">
              {item.chunkErrorMessage}
            </div>
          ) : null}

          <div className="px-4 pt-4">
            <KnowledgeChunkSelector
              chunkCount={item.chunkCount}
              chunkStatus={item.chunkStatus}
              disabled={disabled}
              fileId={item.fileId}
              knowledgeBaseId={knowledgeBaseId}
              key={getKnowledgeChunkSelectorKey(
                item.chunkStatus,
                item.chunkCount,
                item.updatedAt
              )}
              t={t}
            />
          </div>

          <div className="space-y-3 p-4">
            {document.blocks.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border/80 px-4 py-8 text-center text-muted-foreground text-sm">
                {t("settings.noParsedBlocks")}
              </p>
            ) : (
              document.blocks.map((block, index) => (
                <article
                  className="rounded-xl border border-border/70 bg-card/60 p-4"
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
            {document.truncated ? (
              <p className="text-muted-foreground text-xs">
                {t("settings.parsedDocumentTruncated", {
                  count: document.totalBlocks ?? document.blocks.length,
                })}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-muted-foreground text-xs">
          {t("settings.parsedDocumentUpdatedAt", {
            date: formatDate(item.updatedAt, i18nLanguage, t("common.unknownDate")),
          })}
        </span>
        <Button
          disabled={
            isGeneratingChunks ||
            item.fileStatus !== "ready" ||
            item.chunkStatus === "processing"
          }
          onClick={() => onGenerateChunks(item.fileId)}
          size="sm"
          variant="outline"
        >
          {item.chunkStatus === "processing" ? (
            <LoaderCircleIcon className="animate-spin" />
          ) : (
            <Layers3Icon />
          )}
          {t(getKnowledgeChunkActionLabelKey(item.chunkStatus))}
        </Button>
      </div>
    </article>
  );
}

function KnowledgeChunkSelector({
  chunkCount,
  chunkStatus,
  disabled,
  fileId,
  knowledgeBaseId,
  t,
}: {
  chunkCount: number;
  chunkStatus: string;
  disabled: boolean;
  fileId: string;
  knowledgeBaseId: string;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const [offset, setOffset] = useState(0);
  const [reloadIndex, setReloadIndex] = useState(0);
  const [chunkPage, setChunkPage] = useState<KnowledgeChunkPage | null>(null);
  const [selectedChunkIds, setSelectedChunkIds] = useState<Set<string>>(
    () => new Set()
  );
  const [isLoading, setIsLoading] = useState(
    chunkCount > 0 || chunkStatus === "processing"
  );
  const [isEmbedding, setIsEmbedding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadChunkPage = useCallback(async (pageOffset: number) => {
    setIsLoading(true);
    setError(null);
    setChunkPage(null);
    try {
      const page = await requestBackend<KnowledgeChunkPage>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(fileId)}/chunks?offset=${pageOffset}&limit=${KNOWLEDGE_CHUNK_PAGE_SIZE}`
      );
      setChunkPage(page);
      setSelectedChunkIds(new Set());
    } catch (loadError) {
      setChunkPage(null);
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("settings.unableToLoadKnowledgeChunks")
      );
    } finally {
      setIsLoading(false);
    }
  }, [fileId, knowledgeBaseId, t]);

  useEffect(() => {
    if (chunkStatus === "processing") {
      setIsLoading(true);
      setError(null);
      setChunkPage(null);
      setSelectedChunkIds(new Set());
    } else if (chunkCount > 0) {
      void loadChunkPage(offset);
    } else {
      setIsLoading(false);
      setError(null);
      setChunkPage(null);
      setSelectedChunkIds(new Set());
    }
  }, [chunkCount, chunkStatus, loadChunkPage, offset, reloadIndex]);

  const pageChunkIds = chunkPage?.items.map((chunk) => chunk.chunkId) ?? [];
  const allPageChunksSelected =
    pageChunkIds.length > 0 &&
    pageChunkIds.every((chunkId) => selectedChunkIds.has(chunkId));

  const togglePageSelection = () => {
    setSelectedChunkIds(
      allPageChunksSelected ? new Set() : new Set(pageChunkIds)
    );
  };

  const toggleChunkSelection = (chunkId: string) => {
    setSelectedChunkIds((current) => {
      const next = new Set(current);
      if (next.has(chunkId)) {
        next.delete(chunkId);
      } else {
        next.add(chunkId);
      }
      return next;
    });
  };

  const embedSelectedChunks = async () => {
    const chunkIds = [...selectedChunkIds];
    if (chunkIds.length === 0 || isEmbedding) {
      return;
    }

    setIsEmbedding(true);
    setError(null);
    try {
      const result = await requestBackend<KnowledgeChunkEmbeddingResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/files/${encodeURIComponent(fileId)}/chunks/embeddings`,
        {
          body: JSON.stringify({ chunkIds }),
          method: "POST",
        }
      );
      toast.success(
        t("settings.knowledgeChunksEmbedded", {
          count: result.embeddedCount,
          dimensions: result.dimensions,
          model: result.embeddingModel,
        })
      );
      setSelectedChunkIds(new Set());
      setReloadIndex((current) => current + 1);
    } catch (embedError) {
      const message =
        embedError instanceof Error
          ? embedError.message
          : t("settings.knowledgeChunksEmbeddingFailed");
      setError(message);
      toast.error(message);
    } finally {
      setIsEmbedding(false);
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-border/70 bg-card/40">
      <div className="flex flex-col gap-3 border-b border-border/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h5 className="font-medium text-sm">
            {t("settings.chunkSelectionHeading")}
          </h5>
          <p className="mt-1 text-muted-foreground text-xs">
            {t("settings.chunkSelectionDescription")}
          </p>
        </div>
        {chunkPage && chunkPage.items.length > 0 ? (
          <Button
            disabled={disabled || isEmbedding}
            onClick={togglePageSelection}
            size="sm"
            variant="ghost"
          >
            {t(
              allPageChunksSelected
                ? "settings.clearChunkSelection"
                : "settings.selectChunkPage"
            )}
          </Button>
        ) : null}
      </div>

      {error ? (
        <div className="border-b border-destructive/20 bg-destructive/5 px-4 py-3 text-destructive text-sm" role="alert">
          {error}
        </div>
      ) : isLoading && !chunkPage ? (
        <div className="px-4 py-6">
          <InlineLoadingState message={t("settings.loadingKnowledgeChunks")} />
        </div>
      ) : chunkCount === 0 ? (
        <p className="px-4 py-5 text-muted-foreground text-sm">
          {t("settings.noKnowledgeChunks")}
        </p>
      ) : chunkPage && chunkPage.items.length > 0 ? (
        <>
          <div className="divide-y divide-border/60">
            {chunkPage.items.map((chunk) => (
              <label
                className="flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-muted/40"
                key={chunk.chunkId}
              >
                <input
                  aria-label={t("settings.selectKnowledgeChunk", {
                    index: chunk.chunkIndex + 1,
                  })}
                  checked={selectedChunkIds.has(chunk.chunkId)}
                  className="mt-1 size-4 shrink-0 accent-primary"
                  disabled={disabled || isEmbedding}
                  onChange={() => toggleChunkSelection(chunk.chunkId)}
                  type="checkbox"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">
                      {t("settings.knowledgeChunkNumber", {
                        index: chunk.chunkIndex + 1,
                      })}
                    </Badge>
                    <Badge variant={chunk.isEmbedded ? "default" : "outline"}>
                      {chunk.isEmbedded
                        ? t("settings.chunkEmbedded", {
                            model: chunk.embeddingModel ?? "",
                          })
                        : t("settings.chunkNotEmbedded")}
                    </Badge>
                  </span>
                  <span className="mt-2 block max-h-28 overflow-auto whitespace-pre-wrap text-sm leading-6">
                    {chunk.content}
                  </span>
                </span>
              </label>
            ))}
          </div>

          <div className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-muted-foreground text-xs">
              {t("settings.knowledgeChunksPage", {
                from: chunkPage.offset + 1,
                to: Math.min(chunkPage.offset + chunkPage.items.length, chunkPage.total),
                total: chunkPage.total,
              })}
            </span>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              <Button
                disabled={offset === 0 || isLoading || isEmbedding}
                onClick={() => setOffset(Math.max(0, offset - KNOWLEDGE_CHUNK_PAGE_SIZE))}
                size="sm"
                variant="outline"
              >
                <ChevronLeftIcon />
                {t("settings.previousKnowledgeChunks")}
              </Button>
              <Button
                disabled={chunkPage.nextOffset === null || isLoading || isEmbedding}
                onClick={() => {
                  if (chunkPage.nextOffset !== null) {
                    setOffset(chunkPage.nextOffset);
                  }
                }}
                size="sm"
                variant="outline"
              >
                {t("settings.nextKnowledgeChunks")}
                <ChevronRightIcon />
              </Button>
              <Button
                disabled={disabled || isEmbedding || selectedChunkIds.size === 0}
                onClick={() => void embedSelectedChunks()}
                size="sm"
              >
                {isEmbedding ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <ScanTextIcon />
                )}
                {t(
                  isEmbedding
                    ? "settings.embeddingSelectedChunks"
                    : "settings.embedSelectedChunks",
                  { count: selectedChunkIds.size }
                )}
              </Button>
            </div>
          </div>
        </>
      ) : !isLoading ? (
        <p className="px-4 py-5 text-muted-foreground text-sm">
          {t("settings.noKnowledgeChunks")}
        </p>
      ) : (
        <div className="px-4 py-6">
          <InlineLoadingState message={t("settings.loadingKnowledgeChunks")} />
        </div>
      )}
    </section>
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
