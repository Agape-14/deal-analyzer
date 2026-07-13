"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, CheckCircle2, MapPin, Building2, Sparkles, FileDown, FileText, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { BigScoreRing } from "@/components/deal-detail/score-ring";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { FadeIn } from "@/components/motion";
import { useCurrentUser } from "@/lib/auth-client";
import { api } from "@/lib/api";
import { getHeadlineReturnMetrics } from "@/lib/return-metrics";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DataQualityGate, DealDetail, DealQualitySummary } from "@/lib/types";

const POLL_INTERVAL = 5_000;
const DOCUMENT_REVIEW_TIMEOUT = 45 * 60_000;

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

type PipelineStep = "idle" | "extract" | "verify" | "score";
type PipelineStatus = {
  status?: string;
  step?: string;
  message?: string;
  error?: string | null;
  error_kind?: string | null;
  started_at?: string | null;
  updated_at?: string | null;
  progress_pct?: number | null;
  estimated_total_seconds?: number | null;
};
type QualityResponse = { summary?: DealQualitySummary; stale_flags?: unknown[]; pipeline?: PipelineStatus | null };

export function DealHero({ deal }: { deal: DealDetail }) {
  const router = useRouter();
  const { isAnalyst, loading } = useCurrentUser();
  const metrics = deal.metrics ?? {};
  const [scoring, setScoring] = React.useState(false);
  const [pipelineRunning, setPipelineRunning] = React.useState(false);
  const [pipelineStep, setPipelineStep] = React.useState<PipelineStep>("idle");
  const pipelineStepRef = React.useRef<PipelineStep>("idle");
  const [pipelineStatus, setPipelineStatus] = React.useState<PipelineStatus | null>(
    (metrics as { _pipeline?: PipelineStatus })._pipeline ?? null,
  );
  const mountedRef = React.useRef(true);
  const locationBits = [deal.city, deal.state].filter(Boolean).join(", ") || deal.location;
  const visibleScore = deal.overall_score ?? deal.scores?.provisional_overall ?? null;
  const { headlineMultiple, primaryReturnLabel, primaryReturnValue } = getHeadlineReturnMetrics(deal);
  const gate = deal.scores?.data_quality;
  const reviewSummary = dealReviewSummary(gate);
  const viewerSummary = viewerScoreSummary(gate);
  const reviewStatusName = normalizedPipelineStatus(pipelineStatus);
  const showAnalystTools = !loading && isAnalyst;
  const openAnalystTools = showAnalystTools && (pipelineRunning || reviewStatusName === "failed" || reviewStatusName === "running");
  const docsRead = readableDocumentCount(deal);
  const totalDocs = deal.documents?.length ?? 0;

  const setCurrentPipelineStep = React.useCallback((step: PipelineStep) => {
    pipelineStepRef.current = step;
    setPipelineStep(step);
  }, []);

  React.useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function runPipeline() {
    setPipelineRunning(true);
    setCurrentPipelineStep("extract");

    try {
      await api.post(`/api/deals/${deal.id}/review`);
      setPipelineStatus({ status: "running", step: "extract", message: "Document review started. Reading all uploaded documents." });
      toast.success("Document review started", {
        description: "Reading documents, checking sources, and updating the score.",
        duration: 5000,
      });

      await waitForDocumentReview(deal.id, (status) => {
        setPipelineStatus(status);
        setCurrentPipelineStep(pipelineStepFromStatus(status));
      });
      if (!mountedRef.current) return;

      setPipelineStatus({ status: "complete", step: "score", message: "Document review complete. Values were extracted, source-checked, math-checked, and scored." });
      toast.success("Document review complete", {
        description: "Values were extracted, source-checked, math-checked, and scored.",
      });
      router.refresh();
    } catch (e) {
      const detail = (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message;
      const timeout = isReviewTimeout(detail);
      setPipelineStatus((current) => {
        if (current?.status === "failed") return current;
        const failedStep = pipelineStepRef.current === "idle" ? "extract" : pipelineStepRef.current;
        return {
          status: timeout ? "running" : "failed",
          step: failedStep,
          message: timeout ? "Document review is still running." : "Document review incomplete.",
          error: detail,
          error_kind: timeout ? "timeout" : null,
        };
      });
      if (timeout) {
        toast.warning("Document review is still running", { description: detail });
      } else {
        toast.error("Document review incomplete", { description: detail });
      }
    } finally {
      if (mountedRef.current) {
        setPipelineRunning(false);
        setCurrentPipelineStep("idle");
      }
    }
  }

  async function runScore() {
    setScoring(true);
    try {
      await api.post(`/api/deals/${deal.id}/score`);
      toast.success("Score recalculated", {
        description: "This only uses values already saved from the last document review.",
      });
      router.refresh();
    } catch (e) {
      toast.error("Could not recalculate score", { description: (e as { detail?: string })?.detail });
    } finally {
      setScoring(false);
    }
  }

  const pipelineLabel = pipelineRunning ? pipelineStepLabel(pipelineStep) : "Review documents again";

  return (
    <FadeIn>
      <section className="relative overflow-hidden rounded-2xl border border-border/80 bg-card/90 shadow-[0_24px_80px_-60px_rgba(15,23,42,0.8)]">
        <div className="px-5 pt-5 md:px-6 md:pt-6">
          <Link
            href="/"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border/80 bg-background px-3.5 py-2 text-sm font-semibold text-foreground shadow-sm transition-colors hover:border-primary/45 hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            aria-label="Back to all deals"
          >
            <ArrowLeft className="h-4 w-4" />
            All deals
          </Link>
        </div>

        <div className="grid gap-6 px-5 py-6 md:px-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground mb-2">
              <span>{deal.property_type || "Investment"}</span>
              <span className="opacity-40">/</span>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium",
                  STATUS_STYLES[deal.status] ?? STATUS_STYLES.reviewing,
                )}
              >
                {deal.status}
              </span>
            </div>

            <h1 className="text-display-lg tracking-tight">{deal.project_name}</h1>

            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {locationBits && (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="h-4 w-4" />
                  {locationBits}
                </span>
              )}
              {deal.developer_name && (
                <span className="inline-flex items-center gap-1.5">
                  <Building2 className="h-4 w-4" />
                  {deal.developer_name}
                </span>
              )}
            </div>

            <div className="mt-7 overflow-hidden rounded-xl border border-border/80 bg-background/70">
              <div className="grid grid-cols-2 divide-x divide-y divide-border/70 md:grid-cols-4 md:divide-y-0">
                <Metric label={primaryReturnLabel} value={fmtPct(primaryReturnValue)} />
                <Metric label="Equity Multiple" value={fmtMultiple(headlineMultiple)} />
                <Metric label="Min Investment" value={fmtMoney(deal.minimum_investment)} />
                <Metric label="Documents Read" value={`${docsRead}/${totalDocs || 0}`} />
              </div>
            </div>
          </div>

          <aside className="rounded-xl border border-border/80 bg-background/80 p-4 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">Investment summary</div>
                <div className="mt-2">
                  <ViewerTrustBadge gate={gate} />
                </div>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{viewerSummary}</p>
              </div>
              <div className="shrink-0">
                <BigScoreRing value={visibleScore} size={100} />
              </div>
            </div>

            <div className="mt-4 grid gap-2">
              <Button size="sm" variant="secondary" asChild className="justify-center">
                <a href="#deal-summary">
                  <FileText className="h-4 w-4" />
                  Deal summary
                </a>
              </Button>
              <Button size="sm" variant="outline" asChild className="justify-center">
                <a href={`/api/reports/deal/${deal.id}/pdf`} target="_blank" rel="noreferrer">
                  <FileDown className="h-4 w-4" />
                  Export PDF
                </a>
              </Button>
              {showAnalystTools ? (
                <details
                  id="analyst-tools"
                  open={openAnalystTools}
                  className="group rounded-lg border border-border/80 bg-muted/25"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-muted-foreground marker:hidden hover:text-foreground">
                    <span>Analyst tools</span>
                    <span className="text-[11px] font-medium group-open:hidden">Show</span>
                    <span className="hidden text-[11px] font-medium group-open:inline">Hide</span>
                  </summary>
                  <div className="space-y-3 border-t border-border/70 p-3">
                    <div>
                      <ScoreQualityBadge gate={gate} />
                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{reviewSummary}</p>
                    </div>
                    <div className="grid gap-2">
                      <Button size="sm" onClick={runPipeline} disabled={pipelineRunning || scoring} className="justify-center">
                        {pipelineRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                        {pipelineLabel}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={runScore} disabled={scoring || pipelineRunning}>
                        {scoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                        {scoring ? "Calculating..." : "Recalculate score"}
                      </Button>
                    </div>
                    <PipelineNotice status={pipelineStatus} running={pipelineRunning} />
                    <p className="text-[11px] leading-relaxed text-muted-foreground">
                      Review documents re-reads every uploaded file. Recalculate score only uses values already saved from the last document review.
                    </p>
                  </div>
                </details>
              ) : null}
            </div>
          </aside>
        </div>
      </section>
    </FadeIn>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-4 py-3.5">
      <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-foreground/60">{label}</div>
      <div data-figure className="mt-1.5 truncate text-xl font-extrabold tabular-nums tracking-tight text-foreground">{value}</div>
    </div>
  );
}

function dealReviewSummary(gate?: DataQualityGate): string {
  if (!gate) return "Document review has not produced a confidence gate yet.";
  const stage = String(gate.stage ?? "").toLowerCase();
  const openItems = reviewItemCount(gate);
  const confidence = typeof gate.confidence_score === "number" ? `${Math.round(gate.confidence_score)}% confidence` : "confidence pending";

  if (stage === "verified" && openItems === 0) {
    return `Documents reviewed and source-checked. Score is ready to use with ${confidence}.`;
  }
  if (stage.includes("incomplete")) {
    return `Document review is incomplete. Do not rely on the score until review finishes successfully.`;
  }
  if (openItems > 0) {
    return `Documents reviewed, but ${openItems} item${openItems === 1 ? "" : "s"} still need confirmation before the score is trusted.`;
  }
  return `Documents reviewed. Confirm the review queue before relying on the score.`;
}

function reviewItemCount(gate: DataQualityGate): number {
  const critical = gate.critical_summary;
  const criticalCount =
    (critical?.missing ?? 0) +
    (critical?.conflicted ?? 0) +
    (critical?.bad ?? 0) +
    (critical?.review_only ?? 0);
  const mathFailures = gate.math_summary?.fail ?? gate.math_summary?.blocking?.length ?? 0;
  return criticalCount + mathFailures;
}

function readableDocumentCount(deal: DealDetail): number {
  return (deal.documents ?? []).filter((doc) => doc.has_text).length;
}

function viewerScoreSummary(gate?: DataQualityGate): string {
  if (!gate) return "Current underwriting summary. Analyst details are available if a source check is needed.";
  const stage = String(gate.stage ?? "").toLowerCase();
  const openItems = reviewItemCount(gate);

  if (stage === "verified" && openItems === 0) {
    return "Source-backed underwriting summary ready for comparison and export.";
  }
  if (stage.includes("incomplete")) {
    return "Working summary shown while document review finishes. Analyst details are available below.";
  }
  if (openItems > 0) {
    return "Current working summary. Internal review items are grouped under analyst tools.";
  }
  return "Current underwriting summary ready for review.";
}

function ViewerTrustBadge({ gate }: { gate?: DataQualityGate }) {
  const stage = String(gate?.stage ?? "").toLowerCase();
  const openItems = gate ? reviewItemCount(gate) : 0;
  const verified = stage === "verified" && openItems === 0;
  const incomplete = stage.includes("incomplete");
  const label = verified ? "Ready for comparison" : incomplete ? "Review in progress" : "Working summary";
  const Icon = verified ? CheckCircle2 : AlertCircle;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1",
        verified
          ? "bg-success/15 text-success ring-success/30"
          : incomplete
            ? "bg-warning/15 text-warning ring-warning/30"
            : "bg-primary/10 text-primary ring-primary/25",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

function PipelineNotice({ status, running }: { status: PipelineStatus | null; running: boolean }) {
  if (!status?.status || status.status === "idle") return null;

  const statusName = normalizedPipelineStatus(status);
  const category = pipelineFailureCategory(status);
  const timedOut = category === "timeout";
  const failed = statusName === "failed" && !timedOut;
  const complete = statusName === "complete";
  const active = running || statusName === "running";
  const intermediate = ["extract_complete", "verify_complete"].includes(statusName);
  const copy = pipelineNoticeCopy(status, category);
  const Icon = failed ? AlertCircle : complete ? CheckCircle2 : active ? Loader2 : AlertCircle;
  const progress = pipelineProgress(status);
  const eta = reviewEta(status);
  const compact = complete || (!failed && !timedOut);

  if (compact) {
    return (
      <div
        role="status"
        className={cn(
          "w-full max-w-sm rounded-lg border px-3 py-2 text-xs shadow-sm",
          complete
            ? "border-success/35 bg-success/10 text-success"
            : intermediate
              ? "border-warning/40 bg-warning/10 text-warning"
              : "border-primary/35 bg-primary/10 text-primary",
        )}
      >
        <div className="flex items-center gap-2">
          <Icon className={cn("h-4 w-4 shrink-0", active && !complete && "animate-spin")} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-3">
              <span className="truncate font-semibold">{copy.title}</span>
              {eta && <span className="shrink-0 text-[11px] text-current/75">{eta}</span>}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-current/15">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-700",
                    complete ? "bg-success" : intermediate ? "bg-warning" : "bg-primary",
                  )}
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.08em] text-current/75">
                {progress}%
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      role={failed ? "alert" : "status"}
      className={cn(
        "w-full max-w-md rounded-xl border px-4 py-3 text-xs leading-relaxed shadow-sm",
        failed
          ? "border-destructive/45 bg-destructive/10 text-destructive shadow-destructive/10"
          : complete
            ? "border-success/35 bg-success/10 text-success"
            : intermediate
              ? "border-warning/40 bg-warning/10 text-warning"
              : timedOut
                ? "border-warning/40 bg-warning/10 text-warning"
                : "border-primary/35 bg-primary/10 text-primary",
      )}
    >
      <div className="flex items-start gap-3">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", active && !failed && !complete && "animate-spin")} />
        <div className="min-w-0">
          <div className="font-semibold">{copy.title}</div>
          <div className="mt-2">
            <div className="mb-1 flex items-center justify-between gap-3 text-[10px] font-medium uppercase tracking-[0.1em] text-current/75">
              <span>{progress}% complete</span>
              {eta && <span className="normal-case tracking-normal">{eta}</span>}
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-current/15">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-700",
                  failed ? "bg-destructive" : complete ? "bg-success" : timedOut || intermediate ? "bg-warning" : "bg-primary",
                )}
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
          <div className="mt-1 text-current/85">{copy.message}</div>
          {(failed || timedOut) && (
            <div className="mt-2 rounded-lg bg-card/70 px-3 py-2 text-[11px] text-foreground ring-1 ring-border/70">
              <div className="font-medium">What this means</div>
              <div className="mt-0.5 text-muted-foreground">
                The score may still be based on old or partial extraction results. Do not rely on it until document review finishes successfully.
              </div>
              <div className="mt-2 font-medium">Next step</div>
              <div className="mt-0.5 text-muted-foreground">{copy.nextStep}</div>
              {status.step && (
                <div className="mt-2 text-muted-foreground">
                  {timedOut ? "Last known step" : "Stopped during"}: {status.step}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function pipelineNoticeCopy(status: PipelineStatus, category: string) {
  const statusName = normalizedPipelineStatus(status);
  if (statusName === "complete") {
    return {
      title: "Document review complete",
      message: status.message || "Values were extracted, source-checked, math-checked, and scored.",
      nextStep: "Review any remaining Needs attention items.",
    };
  }
  if (statusName === "extract_complete") {
    return {
      title: "Documents read - source check still needed",
      message: status.message || "Uploaded files were read, but source verification has not finished yet.",
      nextStep: "If this message does not change, click Review documents again to finish source verification and scoring.",
    };
  }
  if (statusName === "verify_complete") {
    return {
      title: "Sources checked - score update still needed",
      message: status.message || "Extracted values were checked against source documents and are ready to score.",
      nextStep: "Click Recalculate score, or click Review documents again to re-read everything from scratch.",
    };
  }
  if (statusName !== "failed") {
    const step = String(status.step ?? "").toLowerCase();
    return {
      title:
        step === "extract"
          ? "Reading documents"
          : step === "verify"
            ? "Checking sources"
            : step === "score"
              ? "Updating score"
              : "Reviewing documents",
      message: status.message || "The deal is being re-read, verified, and scored.",
      nextStep: "Wait for this message to change before relying on the score.",
    };
  }
  if (category === "ai_quota") {
    return {
      title: "Document review incomplete: API quota or credits exhausted",
      message: status.error || "The AI provider quota or credit balance was exhausted before document review finished.",
      nextStep: "Add API credits or update billing, then click Review documents again.",
    };
  }
  if (category === "ai_rate_limit") {
    return {
      title: "Document review incomplete: API rate limit hit",
      message: status.error || "The AI provider rate limit was reached before document review finished.",
      nextStep: "Wait for the rate-limit window to reset, then click Review documents again.",
    };
  }
  if (category === "ai_temporarily_unavailable") {
    return {
      title: "Document review incomplete: AI provider unavailable",
      message: status.error || "The AI provider was temporarily unavailable before document review finished.",
      nextStep: "Wait a few minutes, then click Review documents again.",
    };
  }
  if (category === "timeout") {
    return {
      title: "Document review is taking longer than expected",
      message: status.error || status.message || "The review may still be running in the background.",
      nextStep: "Refresh this page in a few minutes. If it has not advanced, click Review documents again.",
    };
  }
  return {
    title: "Document review incomplete",
    message: status.error || status.message || "Document review did not finish.",
    nextStep: "Fix the issue shown above, then click Review documents again.",
  };
}

function normalizedPipelineStatus(status: PipelineStatus | null): string {
  return String(status?.status ?? "").toLowerCase();
}

function pipelineProgress(status: PipelineStatus | null): number {
  const explicit = Number(status?.progress_pct);
  if (Number.isFinite(explicit)) return Math.max(0, Math.min(100, Math.round(explicit)));
  const statusName = normalizedPipelineStatus(status);
  const step = String(status?.step ?? "").toLowerCase();
  if (statusName === "complete") return 100;
  if (statusName === "extract_complete") return 45;
  if (statusName === "verify_complete") return 82;
  if (statusName === "failed") return 0;
  if (step === "extract") return 12;
  if (step === "verify") return 55;
  if (step === "score") return 92;
  return 5;
}

function reviewEta(status: PipelineStatus | null): string | null {
  const statusName = normalizedPipelineStatus(status);
  if (statusName === "complete") return "Done";
  if (statusName === "failed") return null;
  if (pipelineFailureCategory(status ?? {}) === "timeout") return "Still running";

  const total = Number(status?.estimated_total_seconds);
  const startedAt = status?.started_at ? new Date(status.started_at).getTime() : NaN;
  if (!Number.isFinite(total) || !Number.isFinite(startedAt)) return "Estimating";

  const elapsed = Math.max(0, (Date.now() - startedAt) / 1000);
  const remaining = Math.max(0, total - elapsed);
  if (remaining <= 20) return "Almost done";
  if (remaining < 75) return "About 1 min left";
  return `About ${Math.ceil(remaining / 60)} min left`;
}

function isReviewTimeout(message: string | null | undefined): boolean {
  const text = String(message ?? "").toLowerCase();
  return text.includes("timeout") || text.includes("timed out") || text.includes("taking longer") || text.includes("did not finish");
}

function pipelineFailureCategory(status: PipelineStatus): string {
  const explicit = String(status.error_kind || "").toLowerCase();
  if (explicit) return explicit;
  const text = `${status.error || ""} ${status.message || ""}`.toLowerCase();
  if (isReviewTimeout(text)) return "timeout";
  if (["credit", "credits", "quota", "balance", "billing", "payment", "insufficient_quota", "insufficient quota"].some((token) => text.includes(token))) {
    return "ai_quota";
  }
  if ((text.includes("rate") && text.includes("limit")) || text.includes("429") || text.includes("too many requests")) {
    return "ai_rate_limit";
  }
  if (text.includes("overloaded") || text.includes("529")) return "ai_temporarily_unavailable";
  return "unknown";
}

async function waitForDocumentReview(
  dealId: number,
  onStatus?: (status: PipelineStatus | null) => void,
): Promise<PipelineStatus> {
  const start = Date.now();
  while (Date.now() - start < DOCUMENT_REVIEW_TIMEOUT) {
    await sleep(POLL_INTERVAL);
    const res = await api.get<QualityResponse>(`/api/deals/${dealId}/quality`);
    const polledStatus = res.pipeline ?? null;
    if (polledStatus) onStatus?.(polledStatus);
    const statusName = normalizedPipelineStatus(polledStatus);
    if (statusName === "failed") {
      throw new Error(polledStatus?.error || polledStatus?.message || "Document review failed.");
    }
    if (statusName === "complete") return polledStatus ?? { status: "complete", step: "score" };
  }
  throw new Error("Document review is taking longer than expected. It may still be running in the background. Refresh this page in a few minutes before relying on the score.");
}

function pipelineStepLabel(step: PipelineStep): string {
  switch (step) {
    case "extract":
      return "Reading documents...";
    case "verify":
      return "Checking sources...";
    case "score":
      return "Updating score...";
    default:
      return "Working...";
  }
}

function pipelineStepFromStatus(status: PipelineStatus | null): PipelineStep {
  const step = String(status?.step ?? "").toLowerCase();
  if (step === "extract" || step === "verify" || step === "score") return step;
  const statusName = normalizedPipelineStatus(status);
  if (statusName === "extract_complete") return "verify";
  if (statusName === "verify_complete") return "score";
  return "extract";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
