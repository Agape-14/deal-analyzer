"use client";
import * as React from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";

type Revision = { version: number; created_at: string; status: string; changes: Array<{ path: string; previous_value: unknown; value: unknown; state: string }> };
export function AnalysisHistory({ dealId }: { dealId: number }) {
  const [history, setHistory] = React.useState<Revision[] | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    const controller = new AbortController();
    api.get<Revision[]>(`/api/deals/${dealId}/analysis/history`, { signal: controller.signal }).then(setHistory).catch(e => { if (!controller.signal.aborted) setError(e.message ?? "History could not load."); });
    return () => controller.abort();
  }, [dealId]);
  return <Card className="p-5"><h2 className="text-lg font-semibold">Analysis history</h2><p className="mt-1 text-sm text-muted-foreground">Each revision preserves the facts, evidence and questions used at that point. New inputs do not rewrite earlier revisions.</p>
    {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
    {!history && !error && <p className="mt-3 text-sm" role="status">Loading revisions…</p>}
    {history?.length === 0 && <p className="mt-3 text-sm">No persisted revision yet. Existing data is shown as a preview until its next change.</p>}
    <div className="mt-4 space-y-3">{history?.map(r => <details key={r.version} className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">Revision {r.version} · {new Date(r.created_at).toLocaleString()} · {r.changes.length} changes</summary><ul className="mt-3 space-y-2 text-xs">{r.changes.map(c => <li key={c.path}><strong>{c.path.replaceAll("_", " ")}</strong>: {String(c.previous_value ?? "Missing")} → {String(c.value ?? "Missing")} ({c.state})</li>)}</ul></details>)}</div>
  </Card>;
}
