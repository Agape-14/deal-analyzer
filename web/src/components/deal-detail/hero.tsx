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
import type { DataQualityGate, DealDetail, DealQualitySummary, FieldProvenance } from "@/lib/types";

const POLL_INTERVAL = 5_000;
const POLL_TIMEOUT = 8 * 60_000;

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
  const [pipelineStatus, setPipelineStatus] = React.useState<PipelineStatus | null>(
    (metrics as { _pipeline?: PipelineStatus })._pipeline ?? null,
  );
  const mountedRef = React.useRef(true);
  const locationBits = [deal.city, deal.state].filter(Boolean).join(", ") || deal.location;
  const visibleScore = deal.overall_score ?? deal.scores?.provisional_overall ?? null;
  const tr = (metrics.target_returns ?? {}) as Record<string, unknown>;
  const provenance = (metrics._provenance ?? {}) as ProvenanceMap;
  const headlineIrr = pickTrustedNumber(tr, provenance, ["target_returns.target_irr", "target_returns.net_irr"]) ?? deal.target_irr;
  const headlineMultiple = pickTrustedNumber(tr, provenance, ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"]) ?? deal.target_equity_multiple;

  React.useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function runPipeline() {
    setPipelineRunning(true);
    setPipelineStep("extract");
    const beforeExtract = qualityTimestamp(deal.quality, "extract");
    const beforeVerify = qualityTimestamp(deal.quality, "verify") ?? deal.scores?.data_quality?.verified_at ?? null;

    try {
      await api.post(`/api/deals/${deal.id}/extract`);
      setPipelineStatus({ status: "running", step: "extract", message: "Extraction started. Reading all uploaded documents." });
      toast.success("Extraction started", {
        description: "Reading all uploaded documents again.",
        duration: 5000,
      });

      await waitForQualityTimestamp(deal.id, "extract", beforeExtract, setPipelineStatus);
      if (!mountedRef.current) return;

      setPipelineStep("verify");
      await api.post(`/api/deals/${deal.id}/verify`);
      setPipelineStatus({ status: "running", step: "verify", message: "Verification started. Checking source documents." });
      toast.success("Verification started", {
        description: "Checking extracted values against source documents.",
        duration: 5000,
      });

      await waitForQualityTimestamp(deal.id, "verify", beforeVerify, setPipelineStatus);
      if (!mountedRef.current) return;

      setPipelineStep("score");
      setPipelineStatus({ status: "running", step: "score", message: "Scoring started. Recalculating validation, math checks, and score." });
      await api.post(`/api/deals/${deal.id}/score`);
      setPipelineStatus({ status: "complete", step: "score", message: "Pipeline complete. Extraction, verification, math checks, and scoring finished." });
      toast.success("Pipeline complete", {
        description: "Documents were re-read, verified, math-checked, and scored.",
      });
      router.refresh();
    } catch (e) {
      const detail = (e as { detail?: string; message?: string })?.detail ?? (e as Error)?.message;
      setPipelineStatus({ status: "failed", step: pipelineStep, message: "Pipeline did not finish.", error: detail });
      toast.error("Pipeline did not finish", { description: detail });
    } finally {
      if (mountedRef.current) {
        setPipelineRunning(false);
        setPipelineStep("idle");
      }
    }
  }

  async function runScore() {
    setScoring(true);
    try {
      await api.post(`/api/deals/${deal.id}/score`);
      toast.success("Score recalculated", {
        description: "This used the metrics already extracted into the database.",
      });
      router.refresh();
    } catch (e) {
      toast.error("Could not recalculate score", { description: (e as { detail?: string })?.detail });
    } finally {
      setScoring(false);
    }
  }

  const pipelineLabel = pipelineRunning ? pipelineStepLabel(pipelineStep) : "Re-run pipeline";

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
              Re-run pipeline reads all uploaded documents again. Recalculate score only uses already-extracted metrics.
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

  const failed = status.status === "failed";
  const complete = status.status === "complete";
  const message = failed ? status.error || status.message || "Pipeline did not finish." : status.message;
  const Icon = failed ? AlertCircle : complete ? CheckCircle2 : Loader2;

  return (
    <div
      className={cn(
        "max-w-sm rounded-lg border px-3 py-2 text-[11px] leading-relaxed",
        failed
          ? "border-destructive/40 bg-destructive/10 text-destructive"
          : complete
            ? "border-success/35 bg-success/10 text-success"
            : "border-primary/35 bg-primary/10 text-primary",
      )}
    >
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", running && !failed && !complete && "animate-spin")} />
        <div>
          <div className="font-semibold">
            {failed ? "Pipeline stopped" : complete ? "Pipeline complete" : "Pipeline running"}
          </div>
          {message && <div className="mt-0.5 text-current/80">{message}</div>}
        </div>
      </div>
    </div>
  );
}

async function waitForQualityTimestamp(
  dealId: number,
  kind: "extract" | "verify",
  previous: string | null,
  onStatus?: (status: PipelineStatus | null) => void,
): Promise<string> {
  const start = Date.now();
  while (Date.now() - start < POLL_TIMEOUT) {
    await sleep(POLL_INTERVAL);
    const res = await api.get<QualityResponse>(`/api/deals/${dealId}/quality`);
    if (res.pipeline) onStatus?.(res.pipeline);
    if (res.pipeline?.status === "failed") {
      throw new Error(res.pipeline.error || res.pipeline.message || `${kind === "extract" ? "Extraction" : "Verification"} failed.`);
    }
    const next = qualityTimestamp(res.summary, kind);
    if (next && next !== previous) return next;
  }
  throw new Error(`${kind === "extract" ? "Extraction" : "Verification"} did not finish before the timeout. The pipeline status will stay visible here; check notifications or re-run after any API limits clear.`);
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
      return "Extracting docs...";
    case "verify":
      return "Verifying sources...";
    case "score":
      return "Scoring...";
    default:
      return "Running...";
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
