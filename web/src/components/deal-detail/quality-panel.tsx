"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, AlertTriangle, Clock, RefreshCw, Loader2, Sparkles, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn, fmtDate } from "@/lib/utils";
import type { DealQualitySummary } from "@/lib/types";

const POLL_INTERVAL = 5_000;
const POLL_TIMEOUT = 5 * 60_000;

export function QualityPanel({
  dealId,
  quality,
  documents,
}: {
  dealId: number;
  quality: DealQualitySummary | undefined;
  documents: Array<{ filename: string; extraction_quality?: { quality_score: number | null; ocr_pages: number; empty_pages: number[] } | null }>;
}) {
  const router = useRouter();
  const [busy, setBusy] = React.useState<"extract" | "verify" | null>(null);
  const [expanded, setExpanded] = React.useState(false);
  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  React.useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function startPolling(kind: "extract" | "verify", beforeTs: string | null) {
    if (pollRef.current) clearInterval(pollRef.current);
    const tsField = kind === "extract" ? "last_extracted_at" : "last_verified_at";
    const start = Date.now();

    pollRef.current = setInterval(async () => {
      if (Date.now() - start > POLL_TIMEOUT) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setBusy(null);
        toast.info("Still running — refresh manually when ready.");
        return;
      }
      try {
        const res = await api.get<{ summary: DealQualitySummary }>(`/api/deals/${dealId}/quality`);
        const newTs = (res.summary as Record<string, unknown>)?.[tsField] as string | null;
        if (newTs && newTs !== beforeTs) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(null);
          toast.success(kind === "extract" ? "Extraction complete" : "Verification complete", {
            description: `Trust score: ${computeTrust(res.summary)}%`,
          });
          router.refresh();
        }
      } catch {
        // network blip — keep polling
      }
    }, POLL_INTERVAL);
  }

  async function runExtract() {
    setBusy("extract");
    try {
      const beforeTs = quality?.last_extracted_at ?? null;
      await api.post(`/api/deals/${dealId}/extract`);
      toast.success("Extraction started — page will update automatically when done.", { duration: 5000 });
      startPolling("extract", beforeTs);
    } catch (e) {
      toast.error("Extraction failed to start", { description: (e as { detail?: string })?.detail });
      setBusy(null);
    }
  }

  async function runVerify() {
    setBusy("verify");
    try {
      const beforeTs = quality?.last_verified_at ?? null;
      await api.post(`/api/deals/${dealId}/verify?auto_correct=true`);
      toast.success("Verification started — page will update automatically when done.", { duration: 5000 });
      startPolling("verify", beforeTs);
    } catch (e) {
      toast.error("Verification failed to start", { description: (e as { detail?: string })?.detail });
      setBusy(null);
    }
  }

  const q = quality;
  const total = q?.total_fields ?? 0;

  const trust = React.useMemo(() => {
    if (!q || total === 0) return null;
    return computeTrust(q);
  }, [q, total]);

  const docWarnings = React.useMemo(() => {
    const out: string[] = [];
    for (const d of documents ?? []) {
      const eq = d.extraction_quality;
      if (!eq) continue;
      if ((eq.quality_score ?? 100) < 70) {
        out.push(`${d.filename}: only ${eq.quality_score}% of pages yielded usable text`);
      }
      if (eq.empty_pages?.length) {
        out.push(`${d.filename}: ${eq.empty_pages.length} page${eq.empty_pages.length === 1 ? "" : "s"} empty (p.${eq.empty_pages.slice(0, 5).join(", ")}${eq.empty_pages.length > 5 ? "…" : ""})`);
      }
    }
    return out;
  }, [documents]);

  const lastExtracted = q?.last_extracted_at ?? null;
  const ageDays = lastExtracted
    ? Math.floor((Date.now() - new Date(lastExtracted).getTime()) / 86400000)
    : null;
  const stale = ageDays != null && ageDays >= 60;

  const busyLabel = busy === "extract" ? "Extracting…" : busy === "verify" ? "Verifying…" : null;

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "h-10 w-10 rounded-lg grid place-items-center ring-1",
              trust == null
                ? "bg-muted ring-border text-muted-foreground"
                : trust >= 80
                  ? "bg-success/15 ring-success/30 text-success"
                  : trust >= 60
                    ? "bg-warning/15 ring-warning/30 text-warning"
                    : "bg-destructive/15 ring-destructive/30 text-destructive",
            )}
          >
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold tracking-tight">Data integrity</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {busyLabel
                ? busyLabel
                : total === 0
                  ? "No metrics extracted yet — upload an OM and run extraction."
                  : trust != null
                    ? `Trust score ${trust}% — ${total} tracked field${total === 1 ? "" : "s"}`
                    : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={runExtract} disabled={busy !== null}>
            {busy === "extract" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Re-extract
          </Button>
          <Button size="sm" onClick={runVerify} disabled={busy !== null}>
            {busy === "verify" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Verify against docs
          </Button>
        </div>
      </div>

      {q && total > 0 && (
        <>
          {trust != null && (
            <div className="mt-5">
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <motion.div
                  className={cn(
                    "h-full rounded-full",
                    trust >= 80 ? "bg-success" : trust >= 60 ? "bg-warning" : "bg-destructive",
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: `${trust}%` }}
                  transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
            </div>
          )}

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

          {expanded && (
            <>
              <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Counter
                  label="Verified"
                  value={q.verified}
                  color="text-success"
                  hint={q.verified === 0 ? "Click Verify against docs" : undefined}
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
                      <span className="text-muted-foreground">· {q.confidence}% confidence</span>
                    )}
                  </span>
                )}
              </div>

              {stale && (
                <div className="mt-3 inline-flex items-center gap-2 rounded-md bg-warning/10 text-warning ring-1 ring-warning/30 px-2.5 py-1 text-xs">
                  <AlertTriangle className="h-3 w-3" />
                  Metrics are {ageDays}+ days old — re-extract if newer documents are available.
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

function computeTrust(q: DealQualitySummary): number {
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
