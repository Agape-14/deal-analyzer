"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, AlertTriangle, Clock, RefreshCw, Loader2, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";
import type { DataQualityGate, DealQualitySummary } from "@/lib/types";

const POLL_INTERVAL = 5_000;
const POLL_TIMEOUT = 5 * 60_000;

type QualityPanelValue = DealQualitySummary | DataQualityGate | undefined;

export function QualityPanel({
  dealId,
  quality,
  documents,
}: {
  dealId: number;
  quality: QualityPanelValue;
  documents: Array<{ filename: string; extraction_quality?: { quality_score: number | null; ocr_pages: number; empty_pages: number[] } | null }>;
}) {
  const router = useRouter();
  const [busy, setBusy] = React.useState<"extract" | null>(null);
  const [expanded, setExpanded] = React.useState(false);
  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  React.useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function startPolling(beforeTs: string | null) {
    if (pollRef.current) clearInterval(pollRef.current);
    const start = Date.now();

    pollRef.current = setInterval(async () => {
      if (Date.now() - start > POLL_TIMEOUT) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setBusy(null);
        toast.info("Still running - refresh manually when ready.");
        return;
      }
      try {
        const res = await api.get<{ summary: DealQualitySummary }>(`/api/deals/${dealId}/quality`);
        const newTs = res.summary?.last_extracted_at;
        if (newTs && newTs !== beforeTs) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(null);
          toast.success("Extraction complete", {
            description: "Backend verification and scoring will continue automatically.",
          });
          router.refresh();
        }
      } catch {
        // network blip - keep polling
      }
    }, POLL_INTERVAL);
  }

  async function runExtract() {
    setBusy("extract");
    try {
      const beforeExtractTs = isQualitySummary(quality) ? quality.last_extracted_at : null;
      await api.post(`/api/deals/${dealId}/extract`);
      toast.success("Pipeline started - verification and scoring will run automatically.", { duration: 5000 });
      startPolling(beforeExtractTs);
    } catch (e) {
      toast.error("Pipeline failed to start", { description: (e as { detail?: string })?.detail });
      setBusy(null);
    }
  }

  const q = isQualitySummary(quality) ? quality : undefined;
  const gate = q?.data_quality ?? (isDataQualityGate(quality) ? quality : undefined);
  const total = q?.total_fields ?? 0;

  const trust = React.useMemo(() => {
    if (gate) return Math.max(0, Math.min(100, Math.round(gate.confidence_score ?? 0)));
    if (!q || total === 0) return null;
    return computeProvenanceTrust(q);
  }, [gate, q, total]);

  const gateTone = gate ? gateToneClass(gate, trust) : null;
  const statusText = gate ? gateLabel(gate.stage) : null;

  const docWarnings = React.useMemo(() => {
    const out: string[] = [];
    for (const d of documents ?? []) {
      const eq = d.extraction_quality;
      if (!eq) continue;
      if ((eq.quality_score ?? 100) < 70) {
        out.push(`${d.filename}: only ${eq.quality_score}% of pages yielded usable text`);
      }
      if (eq.empty_pages?.length) {
        out.push(`${d.filename}: ${eq.empty_pages.length} page${eq.empty_pages.length === 1 ? "" : "s"} empty (p.${eq.empty_pages.slice(0, 5).join(", ")}${eq.empty_pages.length > 5 ? "..." : ""})`);
      }
    }
    return out;
  }, [documents]);

  const lastExtracted = q?.last_extracted_at ?? null;
  const ageDays = lastExtracted
    ? Math.floor((Date.now() - new Date(lastExtracted).getTime()) / 86400000)
    : null;
  const stale = ageDays != null && ageDays >= 60;

  const busyLabel = busy === "extract" ? "Running pipeline..." : null;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "h-10 w-10 rounded-lg grid place-items-center ring-1",
              gateTone?.icon ?? (
                trust == null
                  ? "bg-muted ring-border text-muted-foreground"
                  : trust >= 80
                    ? "bg-success/15 ring-success/30 text-success"
                    : trust >= 60
                      ? "bg-warning/15 ring-warning/30 text-warning"
                      : "bg-destructive/15 ring-destructive/30 text-destructive"
              ),
            )}
          >
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-semibold tracking-tight">Data integrity</h3>
              {gate && statusText && (
                <span className={cn("rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ring-1", gateTone?.badge)}>
                  {statusText}
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {busyLabel
                ? busyLabel
                : total === 0 && !gate
                  ? "No metrics extracted yet - upload an OM and run the pipeline."
                  : trust != null
                    ? `${gate ? "Gate confidence" : "Trust score"} ${trust}%${total ? ` - ${total} tracked field${total === 1 ? "" : "s"}` : ""}`
                    : ""}
            </p>
          </div>
        </div>

        <Button size="sm" onClick={runExtract} disabled={busy !== null}>
          {busy === "extract" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Re-run pipeline
        </Button>
      </div>

      {(q || gate) && (total > 0 || trust != null) && (
        <>
          {trust != null && (
            <div className="mt-5">
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <motion.div
                  className={cn(
                    "h-full rounded-full",
                    gateTone?.bar ?? (trust >= 80 ? "bg-success" : trust >= 60 ? "bg-warning" : "bg-destructive"),
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: `${trust}%` }}
                  transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
            </div>
          )}

          {gate?.math_summary?.fail ? (
            <div className="mt-3 inline-flex items-center gap-2 rounded-md bg-destructive/10 text-destructive ring-1 ring-destructive/30 px-2.5 py-1 text-xs">
              <AlertTriangle className="h-3 w-3" />
              {gate.math_summary.fail} failed math check{gate.math_summary.fail === 1 ? "" : "s"} must be resolved before the score is trusted.
            </div>
          ) : null}

          {q && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronDown
                className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")}
              />
              {expanded ? "Hide breakdown" : "Show breakdown"}
            </button>
          )}

          {q && expanded && (
            <>
              <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Counter
                  label="Verified"
                  value={q.verified}
                  color="text-success"
                  hint={q.verified === 0 ? "Pipeline will verify automatically" : undefined}
                />
                <Counter label="Extracted" value={q.extracted} />
                <Counter label="Calculated" value={q.calculated} />
                <Counter label="Manual" value={q.manual} color="text-primary" />
                <Counter label="Conflicts" value={q.conflicting} color={q.conflicting ? "text-destructive" : undefined} />
                <Counter label="Wrong (flagged)" value={q.wrong} color={q.wrong ? "text-destructive" : undefined} />
                <Counter label="Unverifiable" value={q.unverifiable} />
                <Counter label="Locked" value={q.locked} />
              </div>

              <div className="mt-4 pt-4 border-t border-border/60 flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="h-3 w-3" />
                  Last extracted:{" "}
                  <span className={cn("tabular-nums", stale ? "text-warning" : "text-foreground")}>
                    {fmtDate(lastExtracted)}
                    {ageDays != null && ` (${ageDays}d ago)`}
                  </span>
                </span>
                {q.last_verified_at && (
                  <span className="inline-flex items-center gap-1.5">
                    <ShieldCheck className="h-3 w-3" />
                    Last verified: <span className="text-foreground">{fmtDate(q.last_verified_at)}</span>
                    {typeof q.confidence === "number" && (
                      <span className="text-muted-foreground">- {q.confidence}% confidence</span>
                    )}
                  </span>
                )}
              </div>

              {stale && (
                <div className="mt-3 inline-flex items-center gap-2 rounded-md bg-warning/10 text-warning ring-1 ring-warning/30 px-2.5 py-1 text-xs">
                  <AlertTriangle className="h-3 w-3" />
                  Metrics are {ageDays}+ days old - re-run the pipeline if newer documents are available.
                </div>
              )}
            </>
          )}
        </>
      )}

      {docWarnings.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border/60 space-y-1.5">
          <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            Document warnings
          </div>
          {docWarnings.map((w, i) => (
            <div key={i} className="text-xs text-warning flex items-start gap-2">
              <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function isQualitySummary(value: QualityPanelValue): value is DealQualitySummary {
  return Boolean(value && "total_fields" in value && typeof value.total_fields === "number");
}

function isDataQualityGate(value: QualityPanelValue): value is DataQualityGate {
  return Boolean(value && "confidence_score" in value && typeof value.confidence_score === "number");
}

function computeProvenanceTrust(q: DealQualitySummary): number {
  const total = q.total_fields ?? 0;
  if (total === 0) return 0;
  const weighted =
    q.verified * 1 +
    q.calculated * 0.9 +
    q.manual * 1 +
    q.extracted * 0.6 +
    q.unverifiable * 0.7;
  const penalties = q.conflicting * 0.8 + q.wrong * 1.2;
  return Math.max(0, Math.min(100, Math.round(((weighted - penalties) / total) * 100)));
}

function gateLabel(stage: string): string {
  return stage.replace(/_/g, " ");
}

function gateToneClass(gate: DataQualityGate, trust: number | null) {
  if (!gate.can_score || gate.stage === "math_failed" || gate.stage === "conflicting" || gate.stage === "insufficient_source") {
    return {
      icon: "bg-destructive/15 ring-destructive/30 text-destructive",
      badge: "bg-destructive/10 text-destructive ring-destructive/30",
      bar: "bg-destructive",
    };
  }
  if (gate.stage === "needs_review" || gate.stage === "provisional" || (trust ?? 0) < 80) {
    return {
      icon: "bg-warning/15 ring-warning/30 text-warning",
      badge: "bg-warning/10 text-warning ring-warning/30",
      bar: "bg-warning",
    };
  }
  return {
    icon: "bg-success/15 ring-success/30 text-success",
    badge: "bg-success/10 text-success ring-success/30",
    bar: "bg-success",
  };
}

function Counter({
  label,
  value,
  color,
  hint,
}: {
  label: string;
  value: number;
  color?: string;
  hint?: string;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className={cn("text-xl font-semibold tabular-nums mt-1", color)}>{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}
