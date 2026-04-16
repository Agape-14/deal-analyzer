"use client";

/**
 * Diagnostics view — the last N AI operations with their status,
 * timing, tokens, and — for failures — the exception and traceback.
 *
 * This is the "why did extraction fail?" page. Auto-refreshes every
 * 5 seconds so you can click Re-extract on a deal and watch the
 * operation land here live.
 */

import * as React from "react";
import { Loader2, AlertCircle, CheckCircle2, RefreshCw, Trash2, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface Entry {
  id: string;
  operation: string;
  started_at: string;
  duration_ms: number | null;
  status: "ok" | "error" | "in_progress";
  deal_id: number | null;
  doc_id: number | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  error_class: string | null;
  error_message: string | null;
  traceback_excerpt: string | null;
  note: string | null;
  meta: Record<string, unknown>;
  prompt_preview?: string | null;
  response_preview?: string | null;
}

interface Diagnostics {
  counts: {
    total_in_buffer: number;
    returned: number;
    errors_in_buffer: number;
  };
  entries: Entry[];
}

export default function DiagnosticsPage() {
  const [data, setData] = React.useState<Diagnostics | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [onlyErrors, setOnlyErrors] = React.useState(false);
  const [full, setFull] = React.useState(false);
  const [autoRefresh, setAutoRefresh] = React.useState(true);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  const load = React.useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (onlyErrors) params.set("only_errors", "1");
      if (full) params.set("full", "1");
      params.set("limit", "50");
      const res = await api.get<Diagnostics>(`/api/admin/diagnostics?${params.toString()}`);
      setData(res);
    } catch (e) {
      toast.error("Couldn't load diagnostics", {
        description: (e as { detail?: string })?.detail ?? String(e),
      });
    } finally {
      setLoading(false);
    }
  }, [onlyErrors, full]);

  React.useEffect(() => {
    load();
  }, [load]);

  React.useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [autoRefresh, load]);

  async function clearBuffer() {
    try {
      await api.post(`/api/admin/diagnostics/clear`);
      toast.success("Buffer cleared");
      load();
    } catch (e) {
      toast.error("Couldn't clear", { description: (e as { detail?: string })?.detail });
    }
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Diagnostics</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Live operation log. AI pipeline calls — what succeeded, what failed, and why.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            size="sm"
            variant={onlyErrors ? "default" : "secondary"}
            onClick={() => setOnlyErrors((v) => !v)}
          >
            <AlertCircle className="h-3.5 w-3.5" />
            Errors only
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setFull((v) => !v)}>
            {full ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            {full ? "Hide bodies" : "Show bodies"}
          </Button>
          <Button
            size="sm"
            variant={autoRefresh ? "default" : "secondary"}
            onClick={() => setAutoRefresh((v) => !v)}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${autoRefresh ? "animate-spin" : ""}`} />
            {autoRefresh ? "Auto-refresh on" : "Auto-refresh off"}
          </Button>
          <Button size="sm" variant="secondary" onClick={load}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button size="sm" variant="destructive" onClick={clearBuffer}>
            <Trash2 className="h-3.5 w-3.5" />
            Clear buffer
          </Button>
        </div>
      </div>

      {data && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>
            <span className="tabular-nums text-foreground">{data.counts.total_in_buffer}</span> in
            buffer
          </span>
          <span className="opacity-40">·</span>
          <span>
            <span className="tabular-nums text-destructive">
              {data.counts.errors_in_buffer}
            </span>{" "}
            errors
          </span>
          <span className="opacity-40">·</span>
          <span>
            showing <span className="tabular-nums text-foreground">{data.counts.returned}</span>
          </span>
        </div>
      )}

      {loading && !data && (
        <div className="py-16 grid place-items-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {data && data.entries.length === 0 && (
        <Card elevated className="p-10 text-center">
          <p className="text-sm text-muted-foreground">
            {onlyErrors
              ? "No errors in the buffer. Ship it."
              : "No operations yet. Trigger an extraction or verification and they'll appear here."}
          </p>
        </Card>
      )}

      <div className="space-y-3">
        {data?.entries.map((e) => (
          <Card
            key={e.id}
            elevated
            className={`p-4 ${
              e.status === "error"
                ? "ring-1 ring-destructive/30"
                : e.status === "in_progress"
                  ? "ring-1 ring-warning/30"
                  : ""
            }`}
          >
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-3 min-w-0">
                {e.status === "ok" && <CheckCircle2 className="h-4 w-4 text-success shrink-0" />}
                {e.status === "error" && (
                  <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
                )}
                {e.status === "in_progress" && (
                  <Loader2 className="h-4 w-4 animate-spin text-warning shrink-0" />
                )}
                <div className="min-w-0">
                  <div className="text-sm font-medium">
                    {e.operation}
                    {e.deal_id != null && (
                      <span className="text-muted-foreground font-normal"> · deal {e.deal_id}</span>
                    )}
                    {e.note && (
                      <span className="text-muted-foreground font-normal"> · {e.note}</span>
                    )}
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                    <span>{new Date(e.started_at).toLocaleTimeString()}</span>
                    {e.duration_ms != null && (
                      <>
                        <span className="opacity-40">·</span>
                        <span className="tabular-nums">{e.duration_ms} ms</span>
                      </>
                    )}
                    {e.model && (
                      <>
                        <span className="opacity-40">·</span>
                        <span className="font-mono">{e.model}</span>
                      </>
                    )}
                    {e.input_tokens != null && (
                      <>
                        <span className="opacity-40">·</span>
                        <span className="tabular-nums">
                          {e.input_tokens}in + {e.output_tokens}out tok
                        </span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {(e.error_message || e.response_preview || Object.keys(e.meta || {}).length > 0) && (
                <Button size="sm" variant="ghost" onClick={() => toggleExpanded(e.id)}>
                  {expanded.has(e.id) ? "Collapse" : "Expand"}
                </Button>
              )}
            </div>

            {e.status === "error" && (
              <div className="mt-3 pt-3 border-t border-destructive/20">
                <div className="text-xs font-mono text-destructive">
                  {e.error_class}: {e.error_message}
                </div>
              </div>
            )}

            {expanded.has(e.id) && (
              <div className="mt-3 pt-3 border-t border-border/60 space-y-3">
                {e.meta && Object.keys(e.meta).length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                      Meta
                    </div>
                    <pre className="text-[11px] font-mono bg-muted/40 rounded p-2 overflow-x-auto">
                      {JSON.stringify(e.meta, null, 2)}
                    </pre>
                  </div>
                )}

                {e.traceback_excerpt && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-destructive/80 mb-1">
                      Traceback
                    </div>
                    <pre className="text-[11px] font-mono bg-destructive/5 text-destructive/90 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                      {e.traceback_excerpt}
                    </pre>
                  </div>
                )}

                {e.response_preview && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                      Response preview (first 2 KB)
                    </div>
                    <pre className="text-[11px] font-mono bg-muted/40 rounded p-2 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto">
                      {e.response_preview}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
