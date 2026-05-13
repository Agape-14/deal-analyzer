"use client";

import { AlertTriangle, CheckCircle2, Circle, Clock3, FileUp, ScanText, ShieldCheck, Sparkles, Calculator } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn, fmtDate } from "@/lib/utils";
import type { DealDetail, FieldProvenance } from "@/lib/types";

type StepState = "done" | "running" | "blocked" | "pending";
type PipelineMeta = {
  verify_status?: string;
  verify_started_at?: string;
  verify_finished_at?: string;
  last_error?: string | null;
};

type MetricsWithPipeline = Record<string, unknown> & {
  _provenance?: Record<string, FieldProvenance>;
  _verification?: { verified_at?: string; confidence?: number | null };
  _math_checks?: { checked_at?: string; summary?: { fail?: number; warn?: number; pass?: number; total?: number } };
  _pipeline?: PipelineMeta;
};

export function PipelineTimeline({ deal }: { deal: DealDetail }) {
  const metrics = (deal.metrics ?? {}) as MetricsWithPipeline;
  const docs = deal.documents ?? [];
  const latestUpload = latestDate(docs.map((d) => d.upload_date));
  const latestExtraction = latestExtractionDate(metrics._provenance);
  const pipeline = metrics._pipeline ?? {};
  const verificationAt = metrics._verification?.verified_at ?? pipeline.verify_finished_at ?? null;
  const mathAt = metrics._math_checks?.checked_at ?? null;
  const scoreReady = deal.scores?.overall != null || deal.scores?.provisional_overall != null;
  const mathFails = metrics._math_checks?.summary?.fail ?? 0;
  const pipelineFailed = pipeline.verify_status === "failed";

  const steps = [
    {
      label: "Documents uploaded",
      detail: docs.length ? `${docs.length} document${docs.length === 1 ? "" : "s"}` : "Waiting for documents",
      at: latestUpload,
      state: docs.length ? "done" : "pending",
      Icon: FileUp,
    },
    {
      label: "Text extracted",
      detail: docs.some((d) => d.has_text) ? "PDF text is available" : "Waiting for text extraction",
      at: latestUpload,
      state: docs.some((d) => d.has_text) ? "done" : docs.length ? "running" : "pending",
      Icon: ScanText,
    },
    {
      label: "Metrics extracted",
      detail: latestExtraction ? "Underwriting fields populated" : "Waiting for metric extraction",
      at: latestExtraction,
      state: latestExtraction ? "done" : docs.some((d) => d.has_text) ? "running" : "pending",
      Icon: Sparkles,
    },
    {
      label: "Docs verified",
      detail: pipelineFailed ? pipeline.last_error || "Verification failed" : verificationDetail(pipeline.verify_status),
      at: verificationAt,
      state: verificationState(pipeline, latestExtraction, verificationAt),
      Icon: ShieldCheck,
    },
    {
      label: "Math checked",
      detail: mathAt ? (mathFails ? `${mathFails} failed math check${mathFails === 1 ? "" : "s"}` : "Deterministic checks passed") : "Waiting for verification",
      at: mathAt,
      state: mathAt ? (mathFails ? "blocked" : "done") : verificationAt ? "running" : "pending",
      Icon: Calculator,
    },
    {
      label: "Score ready",
      detail: scoreReady ? "Score available" : "Waiting for verified data quality",
      at: null,
      state: scoreReady ? "done" : mathAt && mathFails === 0 ? "running" : "pending",
      Icon: CheckCircle2,
    },
  ] satisfies Array<{ label: string; detail: string; at: string | null; state: StepState; Icon: typeof CheckCircle2 }>;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Document review status</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Upload, extraction, source verification, math checks, and scoring progress for this deal.
          </p>
        </div>
        <PipelineBadge state={overallState(steps)} />
      </div>

      <div className="mt-5 grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {steps.map((step, index) => (
          <div key={step.label} className="relative rounded-lg border border-border/70 bg-background/35 p-3">
            {index < steps.length - 1 && (
              <div className="hidden xl:block absolute left-[calc(100%-2px)] top-6 h-px w-3 bg-border" />
            )}
            <div className="flex items-start gap-2.5">
              <div className={cn("mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md ring-1", stateClass(step.state))}>
                <step.Icon className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium tracking-tight">{step.label}</div>
                <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.detail}</div>
                {step.at && <div className="mt-1 text-[11px] text-muted-foreground">{fmtDate(step.at)}</div>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function PipelineBadge({ state }: { state: StepState }) {
  const label = state === "done" ? "Ready" : state === "blocked" ? "Needs review" : state === "running" ? "Processing" : "Pending";
  const Icon = state === "done" ? CheckCircle2 : state === "blocked" ? AlertTriangle : state === "running" ? Clock3 : Circle;
  return (
    <div className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", stateClass(state))}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </div>
  );
}

function overallState(steps: Array<{ state: StepState }>): StepState {
  if (steps.some((s) => s.state === "blocked")) return "blocked";
  if (steps.every((s) => s.state === "done")) return "done";
  if (steps.some((s) => s.state === "running")) return "running";
  return "pending";
}

function stateClass(state: StepState): string {
  switch (state) {
    case "done":
      return "bg-success/15 text-success ring-success/30";
    case "running":
      return "bg-primary/15 text-primary ring-primary/30";
    case "blocked":
      return "bg-destructive/15 text-destructive ring-destructive/30";
    default:
      return "bg-muted text-muted-foreground ring-border";
  }
}

function verificationState(pipeline: PipelineMeta, latestExtraction: string | null, verifiedAt: string | null): StepState {
  if (pipeline.verify_status === "failed") return "blocked";
  if (pipeline.verify_status === "running") return "running";
  if (verifiedAt) return "done";
  if (latestExtraction) return "running";
  return "pending";
}

function verificationDetail(status: string | undefined): string {
  if (status === "running") return "Verifying against source documents";
  if (status === "complete") return "Source verification complete";
  return "Waiting for extracted metrics";
}

function latestExtractionDate(provenance: Record<string, FieldProvenance> | undefined): string | null {
  if (!provenance) return null;
  return latestDate(Object.values(provenance).map((p) => p?.extracted_at).filter(Boolean) as string[]);
}

function latestDate(values: Array<string | null | undefined>): string | null {
  let latest: Date | null = null;
  let latestRaw: string | null = null;
  for (const value of values) {
    if (!value) continue;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) continue;
    if (!latest || parsed > latest) {
      latest = parsed;
      latestRaw = value;
    }
  }
  return latestRaw;
}
