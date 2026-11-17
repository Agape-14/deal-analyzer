"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ClipboardPaste, Download, FileUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const CODEX_LINK = "codex://new?prompt=" + encodeURIComponent(
  "I will attach a Deal Analyzer review packet. Follow its instructions and output schema. Compare every proposed fact with its cited source and cross-check figures across the packet. Save the resulting JSON object as deal-review-result.json so I can import it into Deal Analyzer.",
);
const MAX_RESULT_BYTES = 512_000;

type Row = {
  path: string;
  label: string;
  unit: string;
  value: string | number;
  current: unknown;
  issue: string;
  evidence: { source_doc_name?: string; source_page?: number; source_sheet?: string; source_cell?: string; source_excerpt?: string };
  context: Record<string, string>;
};

type ReviewState = {
  revision: number;
  job: { status: string; error: string | null } | null;
  draft: {
    id: string;
    provider: "codex" | "openai";
    stale: boolean;
    rows: Row[];
    usage?: { estimated_cost_usd: number | null };
  } | null;
};

function display(value: unknown, unit: string) {
  if (typeof value === "string") return value;
  if (typeof value !== "number") return "—";
  const number = value.toLocaleString("en-US", { maximumFractionDigits: 6 });
  return unit === "percent" ? number + "%" : unit === "multiple" ? number + "×" : number;
}

function errorMessage(error: unknown) {
  const detail = (error as { detail?: unknown })?.detail;
  return typeof detail === "string" ? detail : error instanceof Error ? error.message : "Review could not be saved. Refresh and try again.";
}

function parseResult(text: string): Record<string, unknown> {
  const byteLength = (value: string) => new TextEncoder().encode(value).byteLength;
  const tooLarge = "Use a review result of 512 KB or less.";
  if (text.length > MAX_RESULT_BYTES || byteLength(text) > MAX_RESULT_BYTES) {
    throw new Error(tooLarge);
  }
  const trimmed = text.trim();
  // Codex sometimes wraps an otherwise valid JSON result in a Markdown block.
  const fenced = trimmed.match(/^```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```$/i);
  const invalid = "Use the JSON object that Codex produced.";
  let payload: unknown;
  try {
    payload = JSON.parse(fenced?.[1] ?? trimmed);
  } catch {
    throw new Error(invalid);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(invalid);
  }
  if (byteLength(JSON.stringify(payload)) > MAX_RESULT_BYTES) {
    throw new Error(tooLarge);
  }
  return payload as Record<string, unknown>;
}

export function ReviewDraftPanel({ dealId, revision, refreshKey, ready }: {
  dealId: number;
  revision?: number;
  refreshKey: number;
  ready: boolean;
}) {
  const router = useRouter();
  const base = `/api/deals/${dealId}/review`;
  const [state, setState] = React.useState<ReviewState | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [working, setWorking] = React.useState(false);
  const busy = React.useRef(false);
  const [showPaste, setShowPaste] = React.useState(false);
  const [pastedResult, setPastedResult] = React.useState("");
  const pasteId = React.useId();
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);
  const draft = state?.draft;
  const running = ["queued", "running"].includes(state?.job?.status || "");

  React.useEffect(() => {
    if (working) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function load() {
      try {
        const next = await api.get<ReviewState>(base + "/draft", { signal: controller.signal });
        if (!active || busy.current) return;
        setState(current => current && current.revision > next.revision ? current : next);
        if (["queued", "running"].includes(next.job?.status || "")) timer = setTimeout(load, 3000);
      } catch (err) {
        if (active && !busy.current) setError(errorMessage(err));
      }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [base, revision, refreshKey, working]);

  React.useEffect(() => {
    setSelected(new Set((draft?.rows || []).filter(row => !row.issue && (row.current == null || row.current === row.value)).map(row => row.path)));
  // Polling the same draft should preserve the analyst's selections.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.id, draft?.stale]);

  async function importResult(source: string | File) {
    if (busy.current) return;
    busy.current = true;
    setError("");
    setMessage("");
    setWorking(true);
    try {
      if (typeof source !== "string" && source.size > MAX_RESULT_BYTES) {
        throw new Error("Use a review result of 512 KB or less.");
      }
      const payload = parseResult(typeof source === "string" ? source : await source.text());
      setState(await api.post<ReviewState>(base + "/draft", payload));
      setPastedResult("");
      setShowPaste(false);
      setMessage("Review draft ready.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      busy.current = false;
      setWorking(false);
    }
  }

  async function approve() {
    if (busy.current || !draft || !state || !selected.size) return;
    busy.current = true;
    setWorking(true);
    setError("");
    setMessage("");
    try {
      const result = await api.post<ReviewState & { applied: number }>(base + "/approve", {
        draft_id: draft.id, expected_revision: state.revision, paths: [...selected],
      });
      setState(result);
      setMessage(`${result.applied} ${result.applied === 1 ? "value applied" : "values applied"}. Summary and scoring were refreshed.`);
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      busy.current = false;
      setWorking(false);
    }
  }

  return (
    <section className="mb-5 space-y-3 rounded-xl border border-border/70 bg-muted/20 p-4" id="codex-review" aria-label="Review with Codex and review drafts">
      <div>
        <h4 className="text-sm font-semibold">Review with Codex</h4>
        <p className="mt-1 text-xs text-muted-foreground">
          Download the packet and attach it in Codex. Choose <strong>GPT-6 Astra</strong> with <strong>Extra High</strong> reasoning if available, then import the result here.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {ready && <Button asChild size="sm">
          <a href={base + "/packet"}><Download className="mr-1.5 h-3.5 w-3.5" />Download packet</a>
        </Button>}
        <Button asChild variant="outline" size="sm"><a href={CODEX_LINK}>Open Codex</a></Button>
        <Button type="button" variant="outline" size="sm" disabled={working} onClick={() => fileInput.current?.click()}>
          <FileUp className="mr-1.5 h-3.5 w-3.5" />Import result
        </Button>
        <input ref={fileInput} aria-label="Import Codex review result" type="file" accept=".json,application/json" className="hidden" onChange={event => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) void importResult(file);
        }} />
        <Button type="button" variant="outline" size="sm" disabled={working} aria-expanded={showPaste} aria-controls={pasteId} onClick={() => setShowPaste(current => !current)}>
          <ClipboardPaste className="mr-1.5 h-3.5 w-3.5" />Paste JSON
        </Button>
      </div>
      {showPaste && (
        <form id={pasteId} className="space-y-2" onSubmit={event => {
          event.preventDefault();
          if (pastedResult.trim()) void importResult(pastedResult);
        }}>
          <label htmlFor={pasteId + "-result"} className="block text-xs font-medium">Codex review JSON</label>
          <textarea
            id={pasteId + "-result"}
            rows={6}
            value={pastedResult}
            onChange={event => setPastedResult(event.target.value)}
            disabled={working}
            spellCheck={false}
            autoCapitalize="off"
            autoFocus
            className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button type="submit" size="sm" disabled={working || !pastedResult.trim()}>Check pasted result</Button>
        </form>
      )}
      {!ready && <p className="text-xs text-muted-foreground">The packet is available after the primary documents are read.</p>}
      {running && <p className="text-xs text-muted-foreground" role="status">API credit review {state?.job?.status === "queued" ? "queued" : "in progress"}…</p>}
      {state?.job?.error && !running && !draft && <p className="text-xs text-destructive">{state.job.error}</p>}
      {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
      {message && <p className="text-xs text-muted-foreground" role="status">{message}</p>}
      {draft && (
        <div className="space-y-3 border-t border-border/70 pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h5 className="text-sm font-semibold">{draft.provider === "codex" ? "Codex" : "API credit"} review draft</h5>
            {draft.usage?.estimated_cost_usd != null && (
              <span className="text-xs text-muted-foreground">${draft.usage.estimated_cost_usd.toFixed(3)} estimated API usage</span>
            )}
          </div>
          {draft.stale ? <p className="text-xs text-muted-foreground">The deal or its sources changed. Start a new review or download a fresh packet.</p> :
            draft.rows.length === 0 ? <p className="text-xs text-muted-foreground">This review found no supported values in the source package.</p> : (
              <>
                <p className="text-xs text-muted-foreground">New values with matching quotes are selected. Select any replacements you want to apply.</p>
                <ul className="max-h-[29rem] divide-y divide-border/70 overflow-auto rounded-lg border border-border/70">
                  {draft.rows.map((row, index) => {
                    const changed = row.current != null && row.current !== row.value;
                    const location = row.evidence.source_page ? `page ${row.evidence.source_page}` :
                      [row.evidence.source_sheet, row.evidence.source_cell].filter(Boolean).join(" ");
                    return (
                      <li key={row.path + index} className="space-y-1 px-3 py-2.5 text-xs">
                        <label className="flex items-start gap-2">
                          <input type="checkbox" className="mt-0.5 accent-primary" disabled={!!row.issue || working} checked={!row.issue && selected.has(row.path)} onChange={event => {
                            const checked = event.target.checked;
                            setSelected(current => {
                              const next = new Set(current);
                              if (checked) next.add(row.path);
                              else next.delete(row.path);
                              return next;
                            });
                          }} />
                          <span className="min-w-0 break-words font-medium">
                            {row.label}{row.path.includes(".hold_scenario.") ? " (hold)" : row.path.includes(".sale_scenario.") ? " (sale)" : ""}
                            {" · "}{changed ? `${display(row.current, row.unit)} → ` : ""}{display(row.value, row.unit)}
                          </span>
                        </label>
                        <div className="space-y-1 break-words pl-5 text-muted-foreground">
                          {Object.values(row.context).length > 0 && <p>{Object.values(row.context).join(" · ")}</p>}
                          <p>{[row.evidence.source_doc_name, location].filter(Boolean).join(" · ")}</p>
                          {row.evidence.source_excerpt && <blockquote className="border-l border-border pl-2">{row.evidence.source_excerpt}</blockquote>}
                          {row.issue && <p className="text-warning">{row.issue}</p>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <Button size="sm" type="button" disabled={!selected.size || working} onClick={() => void approve()}>
                  Apply {selected.size || "selected"} {selected.size === 1 ? "value" : "values"}
                </Button>
              </>
            )}
        </div>
      )}
    </section>
  );
}
