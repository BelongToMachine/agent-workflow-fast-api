import {
  BotMessageSquareIcon,
  CheckIcon,
  CircleAlertIcon,
  FileSearchIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SendHorizontalIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineLoadingState } from "@/components/ui/loadingState";
import {
  requestBackend,
  requestBackendEventStream,
} from "@/lib/backend/request";
import { cn } from "@/lib/utils";

type SourceReference = {
  blockId: string;
  dataPath: string;
  evidenceId: string;
  fieldPath: string;
  locator: Record<string, string | number>;
  quote: string;
};

type ReviewBasis = {
  claim: string;
  evidenceRefs: string[];
  fieldPath: string;
};

type ReviewUncertainty = {
  actionRequired?: string | null;
  evidenceRefs: string[];
  explanation: string;
  fieldPath: string;
  reason: string;
};

type ProposalExplanation = {
  basis?: ReviewBasis[];
  candidateRef?: string;
  explanation?: string;
  status?: string;
  uncertainties?: ReviewUncertainty[];
};

type ValidationCheck = {
  name: string;
  status: string;
};

type ImportDiagnostics = {
  checks?: ValidationCheck[];
  code?: string;
  details?: Record<string, unknown>;
  message?: string;
  outcome?: string;
  stage?: string;
};

type StreamStage = {
  stage: string;
};

type BusinessImportProposal = {
  appliedAt: string | null;
  candidateRef: string;
  errorMessage: string | null;
  patch: {
    documents?: Array<Record<string, unknown>>;
    operation?: Record<string, unknown> | null;
    prices?: Array<Record<string, unknown>>;
    product?: Record<string, unknown>;
    unresolved?: Array<Record<string, unknown>>;
  };
  proposalId: string;
  reviewExplanation: ProposalExplanation;
  sourceReferences: SourceReference[];
  status: string;
};

type ReviewReport = {
  candidateExplanations?: ProposalExplanation[];
  diagnostics?: ImportDiagnostics;
  streamText?: string;
  summary?: string;
  unclassifiedFindings?: Array<Record<string, unknown>>;
};

type BusinessImportJob = {
  createdAt?: string;
  errorMessage: string | null;
  jobId: string;
  model?: string;
  profile?: string;
  proposals: BusinessImportProposal[];
  promptVersion?: string;
  rawProviderOutput?: string | null;
  reviewReport: ReviewReport | null;
  schemaVersion?: string;
  status: string;
  updatedAt?: string;
};

type BusinessImportJobListResponse = {
  jobs: BusinessImportJob[];
};

type Props = {
  disabled: boolean;
  isOpen: boolean;
  knowledgeBaseId: string;
  onOpenChange: (isOpen: boolean) => void;
  parsedDocumentId: string;
};

function shouldLoadBusinessImportJobs(isOpen: boolean) {
  return isOpen;
}

function formatLocator(locator: Record<string, string | number>) {
  return Object.entries(locator)
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
}

function proposalStatusVariant(
  status: string
): "default" | "destructive" | "outline" | "secondary" {
  if (status === "applied") {
    return "default";
  }
  if (status === "failed" || status === "rejected") {
    return "destructive";
  }
  if (status === "approved") {
    return "secondary";
  }
  return "outline";
}

function displayProductName(proposal: BusinessImportProposal) {
  const value = proposal.patch.product?.productName;
  return typeof value === "string" && value.trim()
    ? value
    : proposal.candidateRef;
}

function eventDiagnostics(value: unknown): ImportDiagnostics | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as ImportDiagnostics;
}

function stageLabel(
  stage: string,
  t: (key: string, options?: Record<string, unknown>) => string
) {
  const labelKeys: Record<string, string> = {
    analyzing: "settings.businessImportStageAnalyzing",
    persisting: "settings.businessImportStagePersisting",
    validating: "settings.businessImportStageValidating",
  };
  const labelKey = labelKeys[stage];
  return labelKey
    ? t(labelKey)
    : t("settings.businessImportStageOther", { stage });
}

function jsonForDisplay(value: unknown) {
  return JSON.stringify(value, null, 2);
}

export function BusinessImportReview({
  disabled,
  isOpen,
  knowledgeBaseId,
  onOpenChange,
  parsedDocumentId,
}: Props) {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<BusinessImportJob[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [actionProposalId, setActionProposalId] = useState<string | null>(null);
  const [streamDiagnostics, setStreamDiagnostics] =
    useState<ImportDiagnostics | null>(null);
  const [streamStages, setStreamStages] = useState<StreamStage[]>([]);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const endpoint = useMemo(
    () =>
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/parsed-documents/${encodeURIComponent(parsedDocumentId)}/business-imports`,
    [knowledgeBaseId, parsedDocumentId]
  );

  const loadJobs = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await requestBackend<BusinessImportJobListResponse>(endpoint);
      setJobs(response.jobs);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("settings.businessImportLoadFailed")
      );
    } finally {
      setIsLoading(false);
    }
  }, [endpoint, t]);

  useEffect(() => {
    if (shouldLoadBusinessImportJobs(isOpen)) {
      void loadJobs();
    }
  }, [isOpen, loadJobs]);

  const latestJob = jobs[0] ?? null;
  const visibleReport = streamText || latestJob?.reviewReport?.streamText || "";
  const summary = latestJob?.reviewReport?.summary;
  const diagnostics = streamDiagnostics ?? latestJob?.reviewReport?.diagnostics ?? null;
  const hasApprovedProposals =
    latestJob?.proposals.some((proposal) => proposal.status === "approved") ??
    false;

  const analyze = useCallback(async () => {
    if (disabled || isAnalyzing) {
      return;
    }
    setError(null);
    setStreamDiagnostics(null);
    setStreamStages([]);
    setStreamText("");
    setIsAnalyzing(true);
    try {
      await requestBackendEventStream(
        `${endpoint}/stream`,
        { body: JSON.stringify({ profile: "product_and_price" }), method: "POST" },
        (event) => {
          if (event.type === "text-delta" && typeof event.delta === "string") {
            setStreamText((current) => current + event.delta);
          }
          if (event.type === "status" && typeof event.stage === "string") {
            setStreamStages((current) => [
              ...current,
              { stage: event.stage },
            ]);
          }
          if (event.type === "result") {
            setStreamDiagnostics(eventDiagnostics(event.diagnostics));
          }
          if (event.type === "error" && typeof event.message === "string") {
            setError(event.message);
            setStreamDiagnostics(eventDiagnostics(event.diagnostics));
          }
        }
      );
      await loadJobs();
    } catch (analysisError) {
      setError(
        analysisError instanceof Error
          ? analysisError.message
          : t("settings.businessImportAnalysisFailed")
      );
    } finally {
      setIsAnalyzing(false);
    }
  }, [disabled, endpoint, isAnalyzing, loadJobs, t]);

  const decideProposal = useCallback(
    async (proposalId: string, decision: "approve" | "reject") => {
      if (!latestJob || actionProposalId) {
        return;
      }
      setActionProposalId(proposalId);
      setError(null);
      try {
        await requestBackend(
          `/api/v1/business-import-jobs/${encodeURIComponent(latestJob.jobId)}/proposals/${encodeURIComponent(proposalId)}/${decision}`,
          { body: JSON.stringify({}), method: "POST" }
        );
        await loadJobs();
        toast.success(
          decision === "approve"
            ? t("settings.businessImportProposalApproved")
            : t("settings.businessImportProposalRejected")
        );
      } catch (decisionError) {
        setError(
          decisionError instanceof Error
            ? decisionError.message
            : t("settings.businessImportDecisionFailed")
        );
      } finally {
        setActionProposalId(null);
      }
    },
    [actionProposalId, latestJob, loadJobs, t]
  );

  const applyApproved = useCallback(async () => {
    if (!latestJob || isApplying || !hasApprovedProposals) {
      return;
    }
    setIsApplying(true);
    setError(null);
    try {
      await requestBackend(
        `/api/v1/business-import-jobs/${encodeURIComponent(latestJob.jobId)}/apply`,
        { body: JSON.stringify({}), method: "POST" }
      );
      await loadJobs();
      toast.success(t("settings.businessImportApplied"));
    } catch (applyError) {
      setError(
        applyError instanceof Error
          ? applyError.message
          : t("settings.businessImportApplyFailed")
      );
    } finally {
      setIsApplying(false);
    }
  }, [hasApprovedProposals, isApplying, latestJob, loadJobs, t]);

  return (
    <Dialog onOpenChange={onOpenChange} open={isOpen}>
      <DialogContent
        className="max-h-[calc(100dvh-1rem)] max-w-[calc(100%-1rem)] gap-0 overflow-hidden p-0 sm:max-w-4xl"
        showCloseButton={false}
      >
        <section className="flex min-h-0 max-h-[calc(100dvh-1rem)] flex-col">
          <DialogHeader className="flex-none border-b border-border/70 px-5 py-5 sm:px-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-violet-500/10 text-violet-700 dark:text-violet-300">
            <BotMessageSquareIcon className="size-4" />
          </span>
          <div>
            <p className="text-muted-foreground text-xs uppercase tracking-[0.13em]">
              {t("settings.businessImportEyebrow")}
            </p>
            <DialogTitle className="mt-1 font-semibold text-base leading-5">
              {t("settings.businessImportHeading")}
            </DialogTitle>
            <DialogDescription className="mt-1 max-w-2xl leading-6">
              {t("settings.businessImportDescription")}
            </DialogDescription>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            aria-label={t("settings.refreshBusinessImport")}
            disabled={isLoading || isAnalyzing}
            onClick={() => void loadJobs()}
            size="icon-sm"
            variant="ghost"
          >
            <RefreshCwIcon className={cn("size-4", isLoading && "animate-spin")} />
          </Button>
          <Button
            disabled={disabled || isAnalyzing}
            onClick={() => void analyze()}
            size="sm"
          >
            {isAnalyzing ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <FileSearchIcon />
            )}
            {isAnalyzing
              ? t("settings.businessImportAnalyzing")
              : t("settings.businessImportAnalyze")}
          </Button>
          <DialogClose asChild>
            <Button aria-label={t("common.close")} size="icon-sm" variant="ghost">
              <XIcon />
            </Button>
          </DialogClose>
        </div>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto">
      {error ? (
        <div className="border-b border-destructive/20 bg-destructive/5 px-5 py-3 text-destructive text-sm sm:px-6" role="alert">
          {error}
        </div>
      ) : null}

      {isLoading && !latestJob ? (
        <div className="px-5 py-8 sm:px-6">
          <InlineLoadingState message={t("settings.loadingBusinessImport")} />
        </div>
      ) : null}

      {isAnalyzing || visibleReport ? (
        <div className="border-b border-border/70 px-5 py-4 sm:px-6">
          <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
            {isAnalyzing ? <LoaderCircleIcon className="size-3.5 animate-spin" /> : <SendHorizontalIcon className="size-3.5" />}
            <span>{isAnalyzing ? t("settings.businessImportLiveOutput") : t("settings.businessImportReviewReport")}</span>
          </div>
          <p className="whitespace-pre-wrap text-sm leading-6">
            {visibleReport || t("settings.businessImportWaitingForOutput")}
          </p>
          {summary ? <p className="mt-3 text-muted-foreground text-xs">{summary}</p> : null}
        </div>
      ) : null}

      {latestJob?.errorMessage ? (
        <div className="flex gap-2 border-b border-destructive/20 bg-destructive/5 px-5 py-3 text-destructive text-sm sm:px-6">
          <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
          <span>{latestJob.errorMessage}</span>
        </div>
      ) : null}

      {latestJob || streamStages.length > 0 || diagnostics ? (
        <TechnicalDetails
          diagnostics={diagnostics}
          job={latestJob}
          streamStages={streamStages}
          t={t}
        />
      ) : null}

      {latestJob && latestJob.proposals.length > 0 ? (
        <div className="space-y-3 p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-sm">
              {t("settings.businessImportProposalCount", {
                count: latestJob.proposals.length,
              })}
            </p>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{latestJob.status}</Badge>
              <Button
                disabled={disabled || !hasApprovedProposals || isApplying}
                onClick={() => void applyApproved()}
                size="sm"
                variant="outline"
              >
                {isApplying ? <LoaderCircleIcon className="animate-spin" /> : <CheckIcon />}
                {isApplying
                  ? t("settings.businessImportApplying")
                  : t("settings.businessImportApplyApproved")}
              </Button>
            </div>
          </div>
          {latestJob.proposals.map((proposal) => (
            <ProposalCard
              actionProposalId={actionProposalId}
              disabled={disabled}
              key={proposal.proposalId}
              onDecide={decideProposal}
              proposal={proposal}
              t={t}
            />
          ))}
        </div>
      ) : !isLoading && !isAnalyzing && !latestJob ? (
        <p className="px-5 py-8 text-muted-foreground text-sm sm:px-6">
          {t("settings.businessImportEmpty")}
        </p>
      ) : null}
          </div>
        </section>
      </DialogContent>
    </Dialog>
  );
}

function TechnicalDetails({
  diagnostics,
  job,
  streamStages,
  t,
}: {
  diagnostics: ImportDiagnostics | null;
  job: BusinessImportJob | null;
  streamStages: StreamStage[];
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const persistedStage = job ? [{ stage: job.status }] : [];
  const stages = streamStages.length > 0 ? streamStages : persistedStage;
  const checks = diagnostics?.checks ?? [];
  const metadata = [
    [t("settings.businessImportJobId"), job?.jobId],
    [t("settings.businessImportStatus"), job?.status],
    [t("settings.businessImportModel"), job?.model],
    [t("settings.businessImportProfile"), job?.profile],
    [t("settings.businessImportPromptVersion"), job?.promptVersion],
    [t("settings.businessImportSchemaVersion"), job?.schemaVersion],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));

  return (
    <div className="border-b border-border/70 px-5 py-4 sm:px-6">
      <details defaultOpen={job?.status === "failed"}>
        <summary className="cursor-pointer font-medium text-sm hover:text-foreground">
          {t("settings.businessImportTechnicalDetails")}
        </summary>
        <div className="mt-4 space-y-4 text-sm">
          {metadata.length > 0 ? (
            <section>
              <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
                {t("settings.businessImportRunMetadata")}
              </p>
              <dl className="mt-2 grid gap-x-5 gap-y-2 sm:grid-cols-2">
                {metadata.map(([label, value]) => (
                  <div className="min-w-0" key={label}>
                    <dt className="text-muted-foreground text-xs">{label}</dt>
                    <dd className="truncate font-mono text-xs" title={value}>
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          {stages.length > 0 ? (
            <section>
              <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
                {t("settings.businessImportStageTimeline")}
              </p>
              <ol className="mt-2 flex flex-wrap gap-2">
                {stages.map((item, index) => (
                  <li
                    className="rounded-md border border-border/70 bg-muted/35 px-2 py-1 font-mono text-xs"
                    key={`${item.stage}-${index}`}
                  >
                    {stageLabel(item.stage, t)}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          {diagnostics ? (
            <section>
              <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
                {t("settings.businessImportValidationDiagnostics")}
              </p>
              <div className="mt-2 rounded-md border border-border/70 bg-muted/30 p-3">
                <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
                  {diagnostics.outcome ? (
                    <span>
                      {t("settings.businessImportOutcome")}={diagnostics.outcome}
                    </span>
                  ) : null}
                  {diagnostics.stage ? (
                    <span>
                      {t("settings.businessImportStage")}={diagnostics.stage}
                    </span>
                  ) : null}
                  {diagnostics.code ? (
                    <span>
                      {t("settings.businessImportCode")}={diagnostics.code}
                    </span>
                  ) : null}
                </div>
                {diagnostics.message ? (
                  <p className="mt-2 text-destructive text-xs">
                    {diagnostics.message}
                  </p>
                ) : null}
                {diagnostics.details && Object.keys(diagnostics.details).length > 0 ? (
                  <pre className="mt-3 max-h-48 overflow-auto rounded bg-background/80 p-3 font-mono text-xs leading-5">
                    {jsonForDisplay(diagnostics.details)}
                  </pre>
                ) : null}
              </div>

              {checks.length > 0 ? (
                <div className="mt-3">
                  <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
                    {t("settings.businessImportValidationChecks")}
                  </p>
                  <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                    {checks.map((check) => (
                      <li
                        className="flex items-center justify-between gap-3 rounded-md bg-muted/45 px-3 py-2 font-mono text-xs"
                        key={check.name}
                      >
                        <span>{check.name}</span>
                        <Badge
                          variant={
                            check.status === "passed" ? "secondary" : "outline"
                          }
                        >
                          {check.status}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}

          <section>
            <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
              {t("settings.businessImportRawProviderOutput")}
            </p>
            {job?.rawProviderOutput ? (
              <pre className="mt-2 max-h-80 overflow-auto rounded-md border border-border/70 bg-muted/35 p-3 whitespace-pre-wrap break-words font-mono text-xs leading-5">
                {job.rawProviderOutput}
              </pre>
            ) : (
              <p className="mt-2 text-muted-foreground text-xs">
                {t("settings.businessImportRawOutputUnavailable")}
              </p>
            )}
          </section>
        </div>
      </details>
    </div>
  );
}

function ProposalCard({
  actionProposalId,
  disabled,
  onDecide,
  proposal,
  t,
}: {
  actionProposalId: string | null;
  disabled: boolean;
  onDecide: (proposalId: string, decision: "approve" | "reject") => void;
  proposal: BusinessImportProposal;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const explanation = proposal.reviewExplanation;
  const isPending = proposal.status === "pending";
  const isActing = actionProposalId === proposal.proposalId;
  const prices = proposal.patch.prices ?? [];

  return (
    <article className="rounded-lg border border-border/70 bg-background/65 px-4 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h6 className="font-medium text-sm">{displayProductName(proposal)}</h6>
            <Badge variant={proposalStatusVariant(proposal.status)}>{proposal.status}</Badge>
            {prices.length > 0 ? (
              <span className="text-muted-foreground text-xs">
                {t("settings.businessImportPriceCount", { count: prices.length })}
              </span>
            ) : null}
          </div>
          {explanation.explanation ? (
            <p className="mt-2 text-muted-foreground text-sm leading-6">
              {explanation.explanation}
            </p>
          ) : null}
        </div>
        {isPending ? (
          <div className="flex shrink-0 gap-2">
            <Button
              disabled={disabled || isActing}
              onClick={() => onDecide(proposal.proposalId, "reject")}
              size="sm"
              variant="ghost"
            >
              {isActing ? <LoaderCircleIcon className="animate-spin" /> : <XIcon />}
              {t("settings.businessImportReject")}
            </Button>
            <Button
              disabled={disabled || isActing}
              onClick={() => onDecide(proposal.proposalId, "approve")}
              size="sm"
              variant="outline"
            >
              {isActing ? <LoaderCircleIcon className="animate-spin" /> : <CheckIcon />}
              {t("settings.businessImportApprove")}
            </Button>
          </div>
        ) : null}
      </div>

      {explanation.basis && explanation.basis.length > 0 ? (
        <div className="mt-3 border-t border-border/60 pt-3">
          <p className="text-muted-foreground text-xs uppercase tracking-[0.12em]">
            {t("settings.businessImportBasis")}
          </p>
          <ul className="mt-2 space-y-1.5 text-sm">
            {explanation.basis.map((basis, index) => (
              <li key={`${basis.fieldPath}-${index}`}>{basis.claim}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {explanation.uncertainties && explanation.uncertainties.length > 0 ? (
        <div className="mt-3 border-t border-amber-500/20 pt-3 text-sm">
          <p className="text-amber-800 text-xs uppercase tracking-[0.12em] dark:text-amber-200">
            {t("settings.businessImportUncertainties")}
          </p>
          <ul className="mt-2 space-y-2">
            {explanation.uncertainties.map((uncertainty, index) => (
              <li key={`${uncertainty.fieldPath}-${index}`}>
                <span className="font-medium">{uncertainty.fieldPath}</span>
                <span className="text-muted-foreground"> · {uncertainty.explanation}</span>
                {uncertainty.actionRequired ? (
                  <span className="block text-muted-foreground text-xs">
                    {uncertainty.actionRequired}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {proposal.sourceReferences.length > 0 ? (
        <details className="mt-3 border-t border-border/60 pt-3">
          <summary className="cursor-pointer text-muted-foreground text-xs hover:text-foreground">
            {t("settings.businessImportEvidence", {
              count: proposal.sourceReferences.length,
            })}
          </summary>
          <div className="mt-3 space-y-2">
            {proposal.sourceReferences.map((reference) => (
              <div className="rounded-md bg-muted/45 px-3 py-2 text-xs" key={reference.evidenceId}>
                <p className="text-muted-foreground">
                  {reference.fieldPath} · {reference.blockId} · {formatLocator(reference.locator)}
                </p>
                <p className="mt-1 whitespace-pre-wrap">“{reference.quote}”</p>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      <details className="mt-3 border-t border-border/60 pt-3">
        <summary className="cursor-pointer text-muted-foreground text-xs hover:text-foreground">
          {t("settings.businessImportStructuredProposal")}
        </summary>
        <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-muted/45 p-3 whitespace-pre-wrap break-words font-mono text-xs leading-5">
          {jsonForDisplay({
            candidateRef: proposal.candidateRef,
            patch: proposal.patch,
            reviewExplanation: proposal.reviewExplanation,
          })}
        </pre>
      </details>

      {proposal.errorMessage ? (
        <p className="mt-3 text-destructive text-xs">{proposal.errorMessage}</p>
      ) : null}
    </article>
  );
}
