"use client";

import * as React from "react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

type Source = { document_id: number; document_name: string; page?: number | null; sheet?: string | null; cell?: string | null; excerpt?: string; content_hash?: string };
type Excerpt = { text: string; included_in_review: boolean; hash_matches: boolean; analysis_version: number; truncated: boolean };

export function EvidenceViewer({ source }: { source: Source }) {
  const [open, setOpen] = React.useState(false);
  const [data, setData] = React.useState<Excerpt | null>(null);
  const [error, setError] = React.useState(false);
  const [retry, reload] = React.useReducer(n => n + 1, 0);
  React.useEffect(() => {
    if (!open) return;
    let active = true;
    setData(null); setError(false);
    const params = new URLSearchParams();
    for (const key of ["page", "sheet", "cell"] as const) if (source[key] != null) params.set(key, String(source[key]));
    if (source.content_hash) params.set("expected_hash", source.content_hash);
    api.get<Excerpt>(`/api/deals/documents/${source.document_id}/excerpt?${params}`).then(value => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [open, source.document_id, source.page, source.sheet, source.cell, source.content_hash, retry]);
  const location = source.page ? `page ${source.page}` : source.sheet ? `${source.sheet} ${source.cell ?? ""}` : "extracted text";
  const quote = source.excerpt?.trim() ?? "";
  const index = data && quote ? data.text.indexOf(quote) : -1;
  return <><button type="button" className="underline text-left text-primary" onClick={() => setOpen(true)}>{source.document_name} · {location}</button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-4xl p-5 max-h-[90vh] overflow-y-auto"><DialogTitle>{source.document_name} · {location}</DialogTitle>
      {error ? <p role="alert" className="my-3">Source text is unavailable. <button onClick={reload} className="underline">Retry source</button> or open the original below.</p> : !data ? <p className="my-3">Loading source…</p> : <>
        <p className="my-3 text-xs text-muted-foreground">Revision {data.analysis_version} · {data.included_in_review && data.hash_matches ? "Current active source" : "Source version changed or excluded from review; recheck the fact"}. Extracted text preserves reported content; visual layout and formulas require the original.</p>
        <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_240px]"><pre className="rounded-lg bg-muted/40 p-4 text-xs leading-relaxed whitespace-pre-wrap break-words max-h-[55vh] overflow-auto">{data.text ? index >= 0 ? <>{data.text.slice(0, index)}<mark className="bg-warning/25 text-foreground">{quote}</mark>{data.text.slice(index + quote.length)}</> : data.text : "No extracted text for this location. Open the original for visual review."}</pre>
          <aside className="text-xs space-y-3"><p className="font-semibold">Supporting quote</p><blockquote className="whitespace-pre-wrap border-l-2 border-primary pl-3">{quote || "No quote recorded."}</blockquote>{quote && index < 0 && <p>Exact quote could not be highlighted at this location. Check the original before relying on it.</p>}{data.truncated && <p>This preview is limited to 16,000 characters. Open the original for the complete page or sheet.</p>}</aside></div>
      </>}
      <a className="mt-4 block text-sm underline" href={`/api/deals/documents/${source.document_id}/file${source.page ? `#page=${source.page}` : ""}`} target="_blank" rel="noreferrer">Open / download original</a>
    </DialogContent></Dialog>
  </>;
}
