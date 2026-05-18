"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, CheckCircle2, MapPin, Building2, Sparkles, FileDown, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { BigScoreRing } from "@/components/deal-detail/score-ring";
import { ScoreQualityBadge } from "@/components/deal-detail/score-quality-badge";
import { FadeIn } from "@/components/motion";
import { api } from "@/lib/api";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { CanonicalReturnSummary, DataQualityGate, DealDetail, DealQualitySummary, FieldProvenance } from "@/lib/types";

const POLL_INTERVAL = 5_000;
const REVIEW_STEP_TIMEOUTS: Record<"extract" | "verify", number> = {
  extract: 20 * 60_000,
  verify: 12 * 60_000,
};

const STATUS_STYLES: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};

type ProvenanceMap = Record<string, FieldProvenance | undefined>;
type PipelineStep = "idle" | "extract" | "verify" | "score";
type PipelineStatus = {
  status?: string;
  step?: string;
  message?: string;
  error?: string | null;
  error_kind?: string | null;
  started_at?: string | null;
  updated_at?: string | null;
};
type QualityResponse = { summary?: DealQualitySummary; stale_flags?: unknown[]; pipeline?: PipelineStatus | null };

export function DealHero({ deal }: { deal: DealDetail }) {
  const router = useRouter();
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
  const tr = (metrics.target_returns ?? {}) as Record<string, unknown>;
  const provenance = (metrics._provenance ?? {}) as ProvenanceMap;
  const canonical = (metrics as { _canonical_returns?: CanonicalReturnSummary })._canonical_returns;
  const headlineIrr =
    asNum(canonical?.target_irr) ??
    pickTrustedNumber(tr, provenance, ["target_returns.target_irr", "target_returns.net_irr"]) ??
    deal.target_irr;
  const headlineMultiple =
    asNum(canonical?.target_equity_multiple) ??
    pickTrustedNumber(tr, provenance, ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"]) ??
    deal.target_equity_multiple;

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
    const beforeExtract = qualityTimestamp(deal.quality, "extract");
    const beforeVerify = qualityTimestamp(deal.quality, "verify") ?? deal.scores?.data_quality?.verified_at ?? null;

    try {
      await api.post(`/api/deals/${deal.id}/extract`);
      setPipelineStatus({ status: "running", step: "extract", message: "Document review started. Reading all uploaded documents." });
      toast.success("Document review started", {
        description: "Reading PDFs, Excel files, and saved document text.",
        duration: 5000,
      });

      await waitForQualityTimestamp(deal.id, "extract", beforeExtract, setPipelineStatus);
      if (!mountedRef.current) return;

      setCurrentPipelineStep("verify");
      await api.post(`/api/deals/${deal.id}/verify`);
      setPipelineStatus({ status: "running", step: "verify", message: "Source verification started. Checking extracted values against source documents." });
      toast.success("Source verification started", {
        description: "Checking extracted values against source documents.",
        duration: 5000,
      });

      await waitForQualityTimestamp(deal.id, "verify", beforeVerify, setPipelineStatus);
      if (!mountedRef.current) return;

      setCurrentPipelineStep("score");
      setPipelineStatus({ status: "running", step: "score", message: "Updating score. Rechecking validation, math checks, and score." });
      await api.post(`/api/deals/${deal.id}/score`);
      setPipelineStatus({ status: "complete", step: "score", message: "Document review complete. Values were extracted, source-checked, math-checked, and scored." });
      toast.success("Document review complete", {
        description: "Values were extracted, source-checked, math-checked, and scored.",
      });
      router.refresh();
    } catch (e) {
      const detail = (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message;
      setPipelineStatus((current) => {
        if (current?.status === "failed") return current;
        const failedStep = pipelineStepRef.current === "idle" ? "extract" : pipelineStepRef.current;
        return {
          status: "failed",
          step: failedStep,
          message: "Document review incomplete.",
          error: detail,
          error_kind: isReviewTimeout(detail) ? "timeout" : null,
        };
      });
      toast.error("Document review incomplete", { description: detail });
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
      <div className="relative">
        <div className="mb-6">
          <Link
            href="/"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border/70 bg-card/70 px-3.5 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:border-primary/45 hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            aria-label="Back to all deals"
          >
            <ArrowLeft className="h-4 w-4" />
            All deals
          </Link>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-8">
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

            <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-6">
              <Metric label="Target IRR" value={fmtPct(headlineIrr)} />
              <Metric label="Equity Multiple" value={fmtMultiple(headlineMultiple)} />
              <Metric label="Min Investment" value={fmtMoney(deal.minimum_investment)} />
              <Metric label="Documents" value={String(deal.documents?.length ?? 0)} />
            </div>
          </div>

          <div className="flex flex-col items-center lg:items-end gap-4">
            <div className="sm:hidden">
              <BigScoreRing value={visibleScore} size={96} />
            </div>
            <div className="hidden sm:block">
              <BigScoreRing value={visibleScore} size={128} />
            </div>
            <ScoreQualityBadge gate={deal.scores?.data_quality} />
            <div className="flex flex-wrap items-center justify-center lg:justify-end gap-2 max-w-sm">
              <Button size="sm" onClick={runPipeline} disabled={pipelineRunning || scoring}>
                {pipelineRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {pipelineLabel}
              </Button>
              <Button size="sm" variant="secondary" onClick={runScore} disabled={scoring || pipelineRunning}>
                {scoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {scoring ? "Calculating..." : "Recalculate score"}
              </Button>
              <Button size="sm" variant="outline" asChild>
                <a href={`/api/reports/deal/${deal.id}/pdf`} target="_blank" rel="noreferrer">
                  <FileDown className="h-4 w-4" />
                  Export PDF
                </a>
              </Button>
            </div>
            <PipelineNotice status={pipelineStatus} running={pipelineRunning} />
            <p className="max-w-sm text-center lg:text-right text-[11px] leading-relaxed text-muted-foreground">
              Review documents again re-reads every uploaded file and rechecks sources. Recalculate score only uses values already saved from the last document review.
            </p>
          </div>
        </div>
      </div>
    </FadeIn>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums tracking-tight mt-1.5">{value}</div>
    </div>
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
          <div className="mt-1 text-current/85">{copy.message}</div>
          {(failed || timedOut) && (
            <div className="mt-2 rounded-lg bg-card/70 px-3 py-2 text-[11px] text-foreground ring-1 ring-border/70">
              <div className="font-medium">What this means</div>
              <div className="mt-0.5 text-muted-foreground">
                The score may still be based on old or partial extraction results. Do not rely on it until document review finishes successfully.
              </div>
              <div className="mt-2 font-medium">Next step</div>
              <div className="mt-0.5 text-muted-foreground">{copy.nextStep}</div>
              {status.step && <div className="mt-2 text-muted-foreground">Stopped during: {status.step}</div>}
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
      message: status.error || "The review may still be running in the background.",
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

async function waitForQualityTimestamp(
  dealId: number,
  kind: "extract" | "verify",
  previous: string | null,
  onStatus?: (status: PipelineStatus | null) => void,
): Promise<string> {
  const start = Date.now();
  while (Date.now() - start < REVIEW_STEP_TIMEOUTS[kind]) {
    await sleep(POLL_INTERVAL);
    const res = await api.get<QualityResponse>(`/api/deals/${dealId}/quality`);
    const polledStatus = res.pipeline ?? null;
    if (polledStatus) onStatus?.(polledStatus);
    if (normalizedPipelineStatus(polledStatus) === "failed") {
      throw new Error(polledStatus?.error || polledStatus?.message || `${kind === "extract" ? "Document reading" : "Source verification"} failed.`);
    }
    const completedAt = documentReviewStepComplete(polledStatus, kind);
    if (completedAt) return completedAt;
    const next = qualityTimestamp(res.summary, kind);
    if (next && next !== previous) return next;
  }
  throw new Error(`${kind === "extract" ? "Document reading" : "Source verification"} is taking longer than expected. The document review may still be running in the background. Refresh this page in a few minutes, or click Review documents again if it has not advanced.`);
}

function documentReviewStepComplete(status: PipelineStatus | null | undefined, kind: "extract" | "verify"): string | null {
  const statusName = normalizedPipelineStatus(status ?? null);
  const completed =
    kind === "extract"
      ? ["extract_complete", "verify_complete", "complete"].includes(statusName)
      : ["verify_complete", "complete"].includes(statusName);
  if (!completed) return null;
  return status?.updated_at ?? status?.started_at ?? new Date().toISOString();
}

function qualityTimestamp(quality: DealDetail["quality"] | DealQualitySummary | DataQualityGate | undefined, kind: "extract" | "verify"): string | null {
  if (!quality) return null;
  if (kind === "extract" && "last_extracted_at" in quality) return quality.last_extracted_at ?? null;
  if (kind === "verify") {
    if ("last_verified_at" in quality) return quality.last_verified_at ?? null;
    if ("verified_at" in quality) return quality.verified_at ?? null;
  }
  return null;
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pickTrustedNumber(block: Record<string, unknown>, provenance: ProvenanceMap, paths: string[]): number | null {
  const candidates = paths
    .map((path) => ({ path, value: asNum(block[path.split(".").at(-1) ?? path]), provenance: provenance[path] }))
    .filter((candidate) => candidate.value !== null);

  if (candidates.length === 0) return null;

  const clean = candidates.filter((candidate) => !isBadSource(candidate.provenance));
  const reviewed = clean.find((candidate) => candidate.provenance?.locked || ["manual", "confirmed", "calculated"].includes(String(candidate.provenance?.status ?? "")));
  return (reviewed ?? clean[0] ?? candidates[0]).value;
}

function isBadSource(provenance?: FieldProvenance): boolean {
  if (!provenance) return false;
  const status = String(provenance.status ?? "").toLowerCase();
  const conflictCount = Array.isArray(provenance.conflict) ? provenance.conflict.length : 0;
  return conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status);
}

function asNum(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}
