"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Download, FileUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const CODEX_LINK = "codex://new?prompt=" + encodeURIComponent(
  "I will attach a Deal Analyzer review packet. Read its instructions and output schema, then review the source documents in the packet. Save the resulting JSON object as deal-review-result.json so I can import it into Deal Analyzer.",
);

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
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);
  const draft = state?.draft;
  const running = ["queued", "running"].includes(state?.job?.status || "");

  React.useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function load() {
      try {
        const next = await api.get<ReviewState>(base + "/draft", { signal: controller.signal });
        if (!active) return;
        setState(next);
        if (["queued", "running"].includes(next.job?.status || "")) timer = setTimeout(load, 3000);
      } catch (err) {
        if (active) setError(errorMessage(err));
      }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [base, revision, refreshKey]);

  React.useEffect(() => {
    setSelected(new Set((draft?.rows || []).filter(row => !row.issue && (row.current == null || row.current === row.value)).map(row => row.path)));
  // Polling the same draft should preserve the analyst's selections.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.id, draft?.stale]);

  async function importResult(file?: File) {
    if (!file) return;
    setError("");
    setMessage("");
    setWorking(true);
    try {
      if (file.size > 512_000) throw new Error("Choose a review result smaller than 512 KB.");
      let payload: unknown;
      try {
        payload = JSON.parse(await file.text());
      } catch {
        throw new Error("Choose the JSON result file that Codex saved.");
      }
      setState(await api.post<ReviewState>(base + "/draft", payload));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setWorking(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function approve() {
    if (!draft || !state || !selected.size) return;
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
      setWorking(false);
    }
  }

  return (
    <section className="mb-5 space-y-3 rounded-xl border border-border/70 bg-muted/20 p-4" aria-label="Review with Codex and review drafts">
      <div>
        <h4 className="text-sm font-semibold">Review with Codex</h4>
        <p className="mt-1 text-xs text-muted-foreground">
          Download the packet, attach it in Codex, then import the result here.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {ready && <Button asChild variant="outline" size="sm">
          <a href={base + "/packet"}><Download className="mr-1.5 h-3.5 w-3.5" />Download packet</a>
        </Button>}
        <Button asChild variant="outline" size="sm"><a href={CODEX_LINK}>Open Codex</a></Button>
        <Button type="button" variant="outline" size="sm" disabled={working} onClick={() => fileInput.current?.click()}>
          <FileUp className="mr-1.5 h-3.5 w-3.5" />Import result
        </Button>
        <input ref={fileInput} aria-label="Import Codex review result" type="file" accept=".json,application/json" className="hidden" onChange={event => void importResult(event.target.files?.[0])} />
      </div>
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