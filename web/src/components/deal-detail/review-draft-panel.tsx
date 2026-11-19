"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ClipboardPaste, Download, FileUp, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { ReturnCrosscheck, ReviewCoverageGroup, SourceFinding } from "@/lib/types";
import { EvidenceViewer } from "./evidence-viewer";
import { coverageLabels } from "./review-coverage";
import { ReturnCrosscheckDetails } from "./return-crosscheck";

const CODEX_LINK = "codex://new?prompt=" + encodeURIComponent(
  "I will attach a Deal Analyzer review packet. Follow its instructions and output schema. Check each quote and compare the figures across sources. Return one JSON code block so I can use Paste JSON in Deal Analyzer.",
);
const MAX_RESULT_BYTES = 512_000;

type Row = {
  path: string;
  label: string;
  unit: string;
  value: string | number;
  current: unknown;
  context_changed?: boolean;
  missing_context?: string[];
  issue: string;
  evidence: { source_doc_id?: number; source_doc_name?: string; source_document_hash?: string; source_page?: number; source_sheet?: string; source_cell?: string; source_excerpt?: string; source_value_note?: string;
    source_table_index?: number; source_table_row?: number; source_column_label?: string };
  context: Record<string, string>;
};

type CoverageRow = {
  group: ReviewCoverageGroup;
  status: "not_stated" | "not_applicable";
  reason: string;
  source_doc_ids: number[];
  issue: string;
};

type ReviewState = {
  revision: number;
  job: { status: string; error: string | null } | null;
  draft: {
    id: string;
    provider: "codex" | "openai";
    stale: boolean;
    rows: Row[];
    coverage?: CoverageRow[];
    findings?: Array<Omit<SourceFinding, "status" | "decision"> & { issue: string }>;
    return_crosscheck?: { value: ReturnCrosscheck | null; issue: string } | null;
    reconciliation_warnings?: Array<{ key: string; label: string; detail: string }>;
    usage?: { estimated_cost_usd: number | null };
  } | null;
};

type ReviewSource = {
  status: "ready" | "reading" | "unread" | "missing";
  refreshing: boolean;
  feedback: { text: string; error?: boolean } | null;
  refresh?: () => void;
};

type Handoff = "packet" | "codex" | "result";
type ReviewStep = Handoff | "load" | "retry" | "sources" | "pending" | "approve" | "saved";

const STEP_LABELS: Record<ReviewStep, string> = {
  load: "Checking for a saved review",
  retry: "Could not load the saved review",
  sources: "Get source documents ready",
  pending: "Review in progress",
  packet: "1 of 4 · Download the source packet",
  codex: "2 of 4 · Review the packet in Codex",
  result: "3 of 4 · Return the result to Deal Analyzer",
  approve: "4 of 4 · Resume your saved draft",
  saved: "Review saved",
};

function display(value: unknown, unit: string) {
  if (typeof value === "string") return value;
  if (typeof value !== "number") return "—";
  const number = value.toLocaleString("en-US", { maximumFractionDigits: 6 });
  return unit === "percent" ? number + "%" : unit === "multiple" ? number + "×" : number;
}

function needsAttention(row: Row) {
  return Boolean(row.issue || row.context_changed || row.missing_context?.length || (row.current != null && row.current !== row.value));
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

export function ReviewDraftPanel({ dealId, revision, refreshKey, source }: {
  dealId: number;
  revision?: number;
  refreshKey: number;
  source: ReviewSource;
}) {
  const router = useRouter();
  const base = `/api/deals/${dealId}/review`;
  const [state, setState] = React.useState<ReviewState | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [selectedCoverage, setSelectedCoverage] = React.useState<Set<ReviewCoverageGroup>>(new Set());
  const [selectedFindings, setSelectedFindings] = React.useState<Set<string>>(new Set());
  const [applyCheck, setApplyCheck] = React.useState(false);
  const [operation, setOperation] = React.useState<"import" | "approve" | null>(null);
  const working = operation !== null;
  const busy = React.useRef(false);
  const [showPaste, setShowPaste] = React.useState(false);
  const [pastedResult, setPastedResult] = React.useState("");
  const [handoff, setHandoff] = React.useState<Handoff>("packet");
  const [needsFreshPacket, setNeedsFreshPacket] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");
  const [retry, retryDraft] = React.useReducer((count: number) => count + 1, 0);
  const pasteId = React.useId();
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);
  const draft = state?.draft;
  const routineRows = draft?.rows.filter(row => !needsAttention(row)) ?? [];
  const exceptionRows = draft?.rows.filter(needsAttention) ?? [];
  const savingReview = selectedCoverage.size > 0 || selectedFindings.size > 0 || applyCheck;
  const running = ["queued", "running"].includes(state?.job?.status || "");
  const ready = source.status === "ready";
  const hasDraft = Boolean(draft && !draft.stale);
  const waitingForDraft = !state || (revision != null && state.revision < revision);
  let step: ReviewStep = handoff;
  if (!ready) step = "sources";
  else if (waitingForDraft) step = loadError ? "retry" : "load";
  else if (needsFreshPacket && !hasDraft) step = "packet";
  else if (showPaste && !running) step = "result";
  else if (hasDraft) step = "approve";
  else if (running) step = "pending";
  else if (saved) step = "saved";

  React.useEffect(() => {
    if (working) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function load() {
      try {
        const next = await api.get<ReviewState>(base + "/draft", { signal: controller.signal });
        if (!active || busy.current) return;
        setLoadError("");
        setState(current => current && current.revision > next.revision ? current : next);
        if (["queued", "running"].includes(next.job?.status || "")) timer = setTimeout(load, 3000);
      } catch (err) {
        if (active && !busy.current) setLoadError(errorMessage(err));
      }
    }
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [base, revision, refreshKey, retry, working]);

  React.useEffect(() => {
    setSaved(false);
    setHandoff("packet");
    setNeedsFreshPacket(false);
  }, [dealId, refreshKey]);

  React.useEffect(() => {
    setSelected(new Set((draft?.rows || []).filter(row => !needsAttention(row)).map(row => row.path)));
    setSelectedCoverage(new Set());
    setSelectedFindings(new Set(draft?.findings?.filter(row => !row.issue).map(row => row.id) ?? []));
    setApplyCheck(Boolean(draft?.return_crosscheck?.value && !draft.return_crosscheck.issue));
    if (draft?.stale) {
      setSaved(false);
      setHandoff("packet");
    }
  // Polling the same draft should preserve the analyst's selections.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.id, draft?.stale]);

  async function importResult(source: string | File) {
    if (busy.current) return;
    busy.current = true;
    setError("");
    setMessage("");
    setOperation("import");
    try {
      if (typeof source !== "string" && source.size > MAX_RESULT_BYTES) {
        throw new Error("Use a review result of 512 KB or less.");
      }
      const payload = parseResult(typeof source === "string" ? source : await source.text());
      setState(await api.post<ReviewState>(base + "/draft", payload));
      setSaved(false);
      setNeedsFreshPacket(false);
      setPastedResult("");
      setShowPaste(false);
      setMessage("Review draft ready.");
    } catch (err) {
      setError(errorMessage(err));
      if ((err as { status?: number })?.status === 409) {
        setHandoff("packet");
        setNeedsFreshPacket(true);
      }
    } finally {
      busy.current = false;
      setOperation(null);
    }
  }

  async function approve() {
    if (busy.current || !ready || !draft || draft.stale || !state || waitingForDraft || (!selected.size && !savingReview)) return;
    busy.current = true;
    setOperation("approve");
    setError("");
    setMessage("");
    try {
      const result = await api.post<ReviewState & { applied: number; coverage_applied?: number; findings_applied?: number; return_crosscheck_applied?: boolean }>(base + "/approve", {
        draft_id: draft.id, expected_revision: state.revision, paths: [...selected], coverage_groups: [...selectedCoverage],
        finding_ids: [...selectedFindings], apply_return_crosscheck: applyCheck,
      });
      setState(result);
      setSaved(result.draft == null);
      setShowPaste(false);
      const applied = [
        result.applied ? `${result.applied} ${result.applied === 1 ? "value applied" : "values applied"}` : "",
        result.coverage_applied ? `${result.coverage_applied} coverage ${result.coverage_applied === 1 ? "finding" : "findings"} saved` : "",
        result.findings_applied ? `${result.findings_applied} source ${result.findings_applied === 1 ? "finding" : "findings"} saved` : "",
        result.return_crosscheck_applied ? "Cash-flow check saved" : "",
      ].filter(Boolean);
      setMessage(applied.join(" · ") + ". Summary and scoring were refreshed.");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      busy.current = false;
      setOperation(null);
    }
  }

  function renderRow(row: Row, index: number) {
    const changed = row.current != null && row.current !== row.value;
    const location = row.evidence.source_page ? [
      `page ${row.evidence.source_page}`,
      row.evidence.source_table_index && `table ${row.evidence.source_table_index}, row ${row.evidence.source_table_row}`,
      row.evidence.source_column_label,
    ].filter(Boolean).join(" · ") : [row.evidence.source_sheet, row.evidence.source_cell].filter(Boolean).join(" ");
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
          {row.issue && <p className="text-warning">{row.issue}</p>}
          {!row.issue && row.context_changed && <p className="text-warning">The proposed context differs from the saved context. Check the source before selecting this value.</p>}
          {!row.issue && !!row.missing_context?.length && <p className="text-warning">Confirm the {row.missing_context.join(", ")} before approving this return.</p>}
          {Object.values(row.context).length > 0 && <p>{Object.values(row.context).join(" · ")}</p>}
          <p>{[row.evidence.source_doc_name, location].filter(Boolean).join(" · ")}</p>
          {row.evidence.source_excerpt && <blockquote className="border-l border-border pl-2">{row.evidence.source_excerpt}</blockquote>}
          {row.evidence.source_value_note && <p>{row.evidence.source_value_note}</p>}
          {row.issue && row.evidence.source_document_hash && row.evidence.source_page &&
            <a href={`/api/deals/documents/${row.evidence.source_doc_id}/file#page=${row.evidence.source_page}`}
              target="_blank" rel="noreferrer" className="inline-block text-primary underline">Open original page</a>}
        </div>
      </li>
    );
  }

  return (
    <section className="mb-5 scroll-mt-20 space-y-3 rounded-xl border border-border/70 bg-muted/20 p-4" id="codex-review" aria-label="Review with Codex and review drafts">
      <div>
        <h4 className="text-sm font-semibold">Review with Codex</h4>
        <p className="mt-1 text-sm font-medium" role="status">
          {operation === "import" ? "Checking the imported result…" : operation === "approve" ? "Saving the reviewed selections…" : STEP_LABELS[step]}
        </p>
        {step === "packet" || step === "codex" ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Attach the downloaded packet in Codex. Choose <strong>GPT-6 Astra</strong> with <strong>Extra High</strong> reasoning if available.
          </p>
        ) : step === "result" ? (
          <p className="mt-1 text-xs text-muted-foreground">Paste the JSON Codex produced or import its saved JSON file.</p>
        ) : step === "approve" ? (
          <p className="mt-1 text-xs text-muted-foreground">Your draft is still here. Check the exceptions and apply the supported selections below.</p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {ready && <Button asChild size="sm" variant={step === "packet" ? "default" : "outline"}>
          <a href={base + "/packet"} onClick={() => {
            setHandoff("codex");
            setNeedsFreshPacket(false);
            setShowPaste(false);
            setSaved(false);
            setError("");
          }}><Download className="mr-1.5 h-3.5 w-3.5" />Download packet</a>
        </Button>}
        {step === "saved" && <Button asChild size="sm">
          <a href={`/deals/${dealId}?tab=overview`}>Open Summary</a>
        </Button>}
        {loadError && <Button type="button" size="sm" variant={step === "retry" ? "default" : "outline"} onClick={retryDraft} disabled={working}>
          Retry loading draft
        </Button>}
        {source.refresh && <Button type="button" size="sm" variant={source.status === "unread" ? "default" : "outline"}
          disabled={source.status === "reading" || running || working} onClick={source.refresh}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5${source.refreshing ? " animate-spin" : ""}`} />
          {source.refreshing ? "Reading original files…" : "Refresh document text"}
        </Button>}
        {source.status === "missing" && <Button asChild size="sm">
          <a href="#deal-documents-upload">Upload a primary document</a>
        </Button>}
        <Button asChild variant={step === "codex" ? "default" : "outline"} size="sm">
          <a href={CODEX_LINK} onClick={() => { setHandoff("result"); setSaved(false); }}>Open Codex</a>
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={working} onClick={() => fileInput.current?.click()}>
          <FileUp className="mr-1.5 h-3.5 w-3.5" />Import result
        </Button>
        <input ref={fileInput} aria-label="Import Codex review result" type="file" accept=".json,application/json" className="hidden" onChange={event => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) void importResult(file);
        }} />
        <Button type="button" variant={step === "result" && !showPaste ? "default" : "outline"}
          size="sm" disabled={working} aria-expanded={showPaste} aria-controls={pasteId} onClick={() => setShowPaste(current => !current)}>
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
          <Button type="submit" size="sm" variant={step === "result" ? "default" : "outline"}
            disabled={working || !pastedResult.trim()}>Check pasted result</Button>
        </form>
      )}
      {source.status === "reading" && !source.feedback && (
        <p className="text-xs text-muted-foreground" role="status">Reading the source documents. The packet will appear when they are ready.</p>
      )}
      {source.status === "unread" && (
        <p className="text-xs text-warning">There is no readable source text. Refresh the document text or upload a readable copy.</p>
      )}
      {source.feedback && (
        <p role={source.feedback.error ? "alert" : "status"} className={source.feedback.error ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
          {source.feedback.text}
        </p>
      )}
      {running && <p className="text-xs text-muted-foreground" role="status">API credit review {state?.job?.status === "queued" ? "queued" : "in progress"}…</p>}
      {state?.job?.error && !running && !draft && <p className="text-xs text-destructive">{state.job.error}</p>}
      {loadError && <p className="text-xs text-destructive" role="alert">{loadError}</p>}
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
          {draft.stale ? <p className="rounded-md border border-warning/30 p-2 text-xs text-warning" role="alert">
            This draft is out of date. The deal or its source files changed. Download a fresh packet before running the review again.
          </p> :
            draft.rows.length === 0 && !draft.coverage?.length && !draft.findings?.length && !draft.return_crosscheck ? <p className="text-xs text-muted-foreground">This review found no supported values in the source package.</p> : (
              <>
                {(exceptionRows.length > 0 || !!draft.reconciliation_warnings?.length) && <section aria-label="Review exceptions" className="space-y-2">
                  <h6 className="text-sm font-medium">Review exceptions</h6>
                  {draft.reconciliation_warnings?.map(check => (
                    <p key={check.key} className="rounded-lg border border-border/70 p-3 text-xs text-warning">
                      <strong>{check.label}</strong> · {check.detail}
                    </p>
                  ))}
                  {exceptionRows.length > 0 && <ul className="max-h-72 divide-y divide-border/70 overflow-auto rounded-lg border border-border/70">
                    {exceptionRows.map(renderRow)}
                  </ul>}
                </section>}
                {routineRows.length > 0 && <details open={routineRows.length <= 5} className="rounded-lg border border-border/70">
                  <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium">
                    {routineRows.filter(row => selected.has(row.path)).length} of {routineRows.length} cited values selected
                  </summary>
                  <ul className="max-h-80 divide-y divide-border/70 overflow-auto border-t border-border/70">
                    {routineRows.map(renderRow)}
                  </ul>
                </details>}
                {!!draft.coverage?.length && (
                  <fieldset className="space-y-2 rounded-lg border border-border/70 p-3 text-xs" disabled={working}>
                    <legend className="px-1 font-medium">Coverage findings</legend>
                    <p className="text-muted-foreground">Confirm a finding after checking the active source documents.</p>
                    {draft.coverage.map(row => (
                      <label className="flex items-start gap-2" key={row.group}>
                        <input type="checkbox" className="mt-0.5 accent-primary" disabled={!!row.issue} checked={!row.issue && selectedCoverage.has(row.group)} onChange={event => {
                          const checked = event.target.checked;
                          setSelectedCoverage(current => {
                            const next = new Set(current);
                            if (checked) next.add(row.group);
                            else next.delete(row.group);
                            return next;
                          });
                        }} />
                        <span className="min-w-0 break-words">
                          <span className="block font-medium">{coverageLabels[row.group]} · {row.status === "not_stated" ? "Not stated" : "Not applicable"}</span>
                          <span className="block text-muted-foreground">{row.reason}</span>
                          {row.issue && <span className="block text-warning">{row.issue}</span>}
                        </span>
                      </label>
                    ))}
                  </fieldset>
                )}
                {!!draft.findings?.length && (
                  <fieldset className="space-y-3 rounded-lg border border-border/70 p-3 text-xs" disabled={working}>
                    <legend className="px-1 font-medium">Source findings</legend>
                    {draft.findings.map((finding, index) => (
                      <div key={`${finding.id}-${index}`} className="space-y-1.5">
                        <label className="flex items-start gap-2 font-medium">
                          <input className="mt-0.5 accent-primary" type="checkbox" disabled={Boolean(finding.issue)}
                            checked={!finding.issue && selectedFindings.has(finding.id)} onChange={event => {
                              const next = new Set(selectedFindings);
                              if (event.target.checked) next.add(finding.id);
                              else next.delete(finding.id);
                              setSelectedFindings(next);
                            }} />
                          {finding.title}
                        </label>
                        <p className="pl-5 text-muted-foreground">{finding.detail}</p>
                        {finding.issue ? <p className="pl-5 text-warning">{finding.issue}</p> : (
                          <div className="flex flex-wrap gap-2 pl-5">
                            {finding.evidence.map((source, position) => (
                              <EvidenceViewer key={`${source.document_id}-${position}`} source={source} />
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </fieldset>
                )}
                {draft.return_crosscheck && (
                  <fieldset className="space-y-2 rounded-lg border border-border/70 p-3" disabled={working}>
                    <legend className="px-1 text-xs font-medium">PDF cash-flow check</legend>
                    <label className="flex items-center gap-2 text-sm font-medium">
                      <input type="checkbox" className="accent-primary" disabled={!draft.return_crosscheck.value || Boolean(draft.return_crosscheck.issue)}
                        checked={applyCheck} onChange={event => setApplyCheck(event.target.checked)} />
                      Save cash-flow check
                    </label>
                    {draft.return_crosscheck.issue && <p className="text-xs text-warning">{draft.return_crosscheck.issue}</p>}
                    {draft.return_crosscheck.value && <ReturnCrosscheckDetails check={draft.return_crosscheck.value} />}
                  </fieldset>
                )}
                <Button size="sm" type="button" variant={step === "approve" ? "default" : "outline"}
                  disabled={(!selected.size && !savingReview) || !ready || working || waitingForDraft} onClick={() => void approve()}>
                  {selected.size ? `Apply ${selected.size} ${selected.size === 1 ? "value" : "values"}${savingReview ? " and save review" : ""}` : savingReview ? "Save review" : "Apply selected values"}
                </Button>
              </>
            )}
        </div>
      )}
    </section>
  );
}
