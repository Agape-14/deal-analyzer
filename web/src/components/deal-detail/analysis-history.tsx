"use client";
import * as React from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/lib/auth-client";
import { useRouter } from "next/navigation";
import type { DealAnalysis } from "@/lib/types";

type Revision = { version: number; created_at: string; status: string; can_restore?: boolean; changes: Array<{ path: string; previous_value: unknown; value: unknown; state: string }> };
type Preview = { expected_revision: number; current: DealAnalysis; candidate: DealAnalysis };
export function AnalysisHistory({ dealId, revision, analysisVersion }: { dealId: number; revision?: number; analysisVersion?: number }) {
  const [history, setHistory] = React.useState<Revision[] | null>(null);
  const [error, setError] = React.useState("");
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const { isAnalyst } = useCurrentUser();
  const router = useRouter();
  React.useEffect(() => {
    const controller = new AbortController();
    api.get<Revision[]>(`/api/deals/${dealId}/analysis/history`, { signal: controller.signal }).then(setHistory).catch(e => { if (!controller.signal.aborted) setError(e.message ?? "History could not load."); });
    return () => controller.abort();
  }, [dealId, revision]);
  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError((e as { detail?: string }).detail ?? (e instanceof Error ? e.message : "Could not save. Reload and try again.")); }
    finally { setBusy(false); }
  }
  return <Card className="p-5"><h2 className="text-lg font-semibold">Analysis history</h2><p className="mt-1 text-sm text-muted-foreground">Each revision preserves the facts, evidence and questions used at that point. New inputs do not rewrite earlier revisions.</p>
    {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
    {!history && !error && <p className="mt-3 text-sm" role="status">Loading revisions…</p>}
    {history?.length === 0 && <p className="mt-3 text-sm">No persisted revision yet. Existing data is shown as a preview until its next change.</p>}
    {isAnalyst && <Button variant="outline" size="sm" className="mt-3" disabled={busy} onClick={() => act(async () => setPreview(await api.get<Preview>(`/api/deals/${dealId}/analysis/preview`)))}>Preview current inputs</Button>}
    {preview && <div className="mt-3 rounded-lg border p-4 text-sm"><p>Current: {preview.current.coverage.accepted} accepted facts, {preview.current.questions.length} question groups.</p><p>Preview: {preview.candidate.coverage.accepted} accepted facts, {preview.candidate.questions.length} question groups.</p><p className="mt-2 text-xs text-muted-foreground">No source values are rewritten. A saved preview uses the current documents and preserves manual locks.</p><ul className="my-3 space-y-1 text-xs">{["cash_on_cash", "target_irr", "target_equity_multiple"].map(key => <li key={key}>{key.replaceAll("_", " ")}: {String(preview.current.returns[key as keyof typeof preview.current.returns] ?? "Withheld")} → {String(preview.candidate.returns[key as keyof typeof preview.candidate.returns] ?? "Withheld")}</li>)}</ul><Button size="sm" disabled={busy} onClick={() => act(async () => { await api.post(`/api/deals/${dealId}/analysis/adopt`, { expected_revision: preview.expected_revision, input_hash: preview.candidate.input_hash }); setPreview(null); router.refresh(); })}>Save reviewed preview</Button></div>}
    <div className="mt-4 space-y-3">{history?.map(r => <details key={r.version} className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">Revision {r.version} · {new Date(r.created_at).toLocaleString()} · {r.changes.length} changes</summary><ul className="mt-3 space-y-2 text-xs">{r.changes.map(c => <li key={c.path}><strong>{c.path.replaceAll("_", " ")}</strong>: {String(c.previous_value ?? "Missing")} → {String(c.value ?? "Missing")} ({c.state})</li>)}</ul>
      {isAnalyst && r.can_restore && r.version !== analysisVersion && <form className="mt-4 space-y-2" onSubmit={e => { e.preventDefault(); void act(async () => { await api.post(`/api/deals/${dealId}/analysis/${r.version}/restore`, { expected_revision: revision, reason }); setReason(""); router.refresh(); }); }}><p className="text-xs text-muted-foreground">Restore this revision&apos;s inputs as a new revision. Current document files remain in place; their evidence is checked again.</p><label className="block text-xs">Reason for restoring<input className="mt-1 block w-full rounded border bg-background p-2" required minLength={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label><Button size="sm" variant="outline" disabled={busy || !revision}>Restore these inputs</Button></form>}
    </details>)}</div>
  </Card>;
}
