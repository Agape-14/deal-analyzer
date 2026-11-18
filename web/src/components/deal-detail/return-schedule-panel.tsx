"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import type { DealDetail, DealDocument, ReturnSchedule } from "@/lib/types";
import { EvidenceViewer } from "./evidence-viewer";

export function ReturnScheduleTable({ schedule }: { schedule: ReturnSchedule }) {
  const source = schedule.evidence[0];
  return (
    <div className="space-y-3 text-sm">
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-3">
        <div><dt className="text-muted-foreground">Investor class</dt><dd>{schedule.investor_class}</dd></div>
        <div><dt className="text-muted-foreground">Periods measured from</dt><dd>{schedule.period_basis}</dd></div>
        <div><dt className="text-muted-foreground">Equity basis</dt><dd>{schedule.equity_basis}</dd></div>
      </dl>
      {schedule.assumptions && <p>{schedule.assumptions}</p>}
      {source && <EvidenceViewer source={{ ...source, cell: undefined }} />}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left" aria-label="Projected cash-on-cash by year">
          <thead><tr className="border-b text-muted-foreground">
            <th scope="col" className="py-2 pr-4">Year</th>
            <th scope="col" className="py-2 pr-4">Projected cash-on-cash</th>
            <th scope="col" className="py-2">Source notes</th>
          </tr></thead>
          <tbody>{schedule.rows.map(row => (
            <tr key={row.year} className="border-b border-border/70 align-top">
              <th scope="row" className="whitespace-nowrap py-2 pr-4 font-medium">Year {row.year}</th>
              <td className="py-2 pr-4 tabular-nums">{row.cash_on_cash_pct == null ? "Unavailable" : `${row.cash_on_cash_pct}%`}</td>
              <td className="py-2">
                {row.note && <p>{row.note}</p>}
                <details className="mt-1 text-xs text-muted-foreground">
                  <summary className="cursor-pointer">Source quote for year {row.year}</summary>
                  {row.source_cell && <p className="mt-1">Cell {row.source_cell}</p>}
                  <blockquote className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words">{row.source_excerpt}</blockquote>
                </details>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

export function ReturnSchedulePanel({ deal }: { deal: DealDetail }) {
  const { isAnalyst, loading } = useCurrentUser();
  const [editing, setEditing] = React.useState(false);
  const schedule = deal.analysis?.return_schedule;
  const sources = deal.documents.filter(doc => doc.has_text && doc.included_in_review !== false
    && (!doc.source_role || doc.source_role === "active"));
  const canEdit = !loading && isAnalyst && !!deal.revision && sources.length > 0
    && ["hold", "hold_with_sale_option"].includes(deal.analysis?.primary_strategy ?? "");
  if (!schedule && !canEdit) return null;
  return (
    <Card className="space-y-4 p-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Projected hold returns</h2>
        {canEdit && !editing && <Button type="button" variant="outline" onClick={() => setEditing(true)}>
          {schedule ? "Edit return schedule" : "Record return schedule"}
        </Button>}
      </div>
      {editing && canEdit
        ? <ReturnScheduleForm deal={deal} sources={sources} onCancel={() => setEditing(false)} />
        : schedule
          ? <ReturnScheduleTable schedule={schedule} />
          : <p className="text-sm text-muted-foreground">Record year-by-year cash-on-cash when the source gives a schedule.</p>}
    </Card>
  );
}

type EditableRow = { year: string; cash_on_cash_pct: string; note: string; source_excerpt: string; source_cell: string };
const blankRow = (year: number): EditableRow => ({ year: String(year), cash_on_cash_pct: "", note: "", source_excerpt: "", source_cell: "" });
const inputClass = "mt-1 w-full rounded-md border border-border bg-background p-2 text-sm";

function ReturnScheduleForm({ deal, sources, onCancel }: { deal: DealDetail; sources: DealDocument[]; onCancel: () => void }) {
  const schedule = deal.analysis?.return_schedule;
  const evidence = schedule?.evidence[0];
  const [sourceId, setSourceId] = React.useState(evidence?.document_id ?? sources[0].id);
  const [page, setPage] = React.useState(String(evidence?.page ?? 1));
  const [sheet, setSheet] = React.useState(evidence?.sheet ?? "");
  const [context, setContext] = React.useState({
    investor_class: schedule?.investor_class ?? "", equity_basis: schedule?.equity_basis ?? "",
    period_basis: schedule?.period_basis ?? "", assumptions: schedule?.assumptions ?? "",
  });
  const [rows, setRows] = React.useState<EditableRow[]>(() => schedule?.rows.map(row => ({
    ...row, year: String(row.year), cash_on_cash_pct: row.cash_on_cash_pct == null ? "" : String(row.cash_on_cash_pct),
    source_cell: row.source_cell ?? "",
  })) ?? [blankRow(1)]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const source = sources.find(doc => doc.id === sourceId);
  const workbook = !!source && /\.(?:xlsx|xlsm|xls|csv)$/i.test(source.filename);

  function changeRow(index: number, key: keyof EditableRow, value: string) {
    setRows(old => old.map((row, i) => i === index ? { ...row, [key]: value } : row));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.put(`/api/deals/${deal.id}/analysis/return-schedule`, {
        expected_revision: deal.revision, source_doc_id: sourceId,
        source_page: workbook ? null : Number(page), source_sheet: workbook ? sheet.trim() : null,
        ...context,
        rows: rows.map(row => ({
          ...row, year: Number(row.year), cash_on_cash_pct: row.cash_on_cash_pct === "" ? null : Number(row.cash_on_cash_pct),
          source_cell: workbook ? row.source_cell.trim() : null,
        })),
      });
      window.location.reload();
    } catch (err) {
      const detail = (err as { detail?: unknown })?.detail;
      setError(typeof detail === "string" ? detail : "The schedule could not be saved. Check each year, number, and source quote.");
      setSaving(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={save}>
      <div className="grid gap-3 sm:grid-cols-3">
        {([ ["investor_class", "Investor class", 100], ["period_basis", "Periods measured from", 180], ["equity_basis", "Equity basis", 180] ] as const).map(([key, label, limit]) => (
          <label key={key} className="block text-sm">{label}<input required maxLength={limit} className={inputClass} value={context[key]} onChange={e => setContext({ ...context, [key]: e.target.value })} /></label>
        ))}
      </div>
      <label className="block text-sm">Model assumptions<textarea maxLength={1000} value={context.assumptions} className={inputClass} onChange={e => setContext({ ...context, assumptions: e.target.value })} /></label>
      <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
        <label className="block text-sm">Source document<select required value={sourceId} className={inputClass} onChange={e => setSourceId(Number(e.target.value))}>
          {sources.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}
        </select></label>
        {workbook
          ? <label className="block text-sm">Source sheet<input required maxLength={128} value={sheet} className={inputClass} onChange={e => setSheet(e.target.value)} /></label>
          : <label className="block text-sm">Source page<input required type="number" min={1} max={source?.page_count || undefined} value={page} className={inputClass} onChange={e => setPage(e.target.value)} /></label>}
      </div>
      {source && <EvidenceViewer source={{
        document_id: source.id, document_name: source.filename, page: workbook ? null : Number(page) || null,
        sheet: workbook ? sheet.trim() || null : null,
      }} />}
      <p className="text-sm text-muted-foreground">Copy the source text for each year, including the year label and its return. Leave the return blank when the source marks it unavailable and explain why.</p>
      {rows.map((row, index) => (
        <fieldset key={index} className="space-y-3 rounded-lg border border-border p-3">
          <legend className="px-1 text-sm font-medium">Projection row {index + 1}</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm">Year<input required type="number" min={1} max={50} aria-label={`Year for row ${index + 1}`} className={inputClass} value={row.year} onChange={e => changeRow(index, "year", e.target.value)} /></label>
            <label className="text-sm">Cash-on-cash (%)<input type="number" step="any" min={-1000} max={1000} aria-label={`Cash-on-cash (%) for row ${index + 1}`} className={inputClass} value={row.cash_on_cash_pct} onChange={e => changeRow(index, "cash_on_cash_pct", e.target.value)} /></label>
            {workbook && <label className="text-sm">Value cell<input required pattern="[A-Za-z]{1,3}[1-9][0-9]*" aria-label={`Value cell for row ${index + 1}`} className={inputClass} value={row.source_cell} onChange={e => changeRow(index, "source_cell", e.target.value)} /></label>}
          </div>
          <label className="block text-sm">Source quote<textarea required minLength={8} maxLength={1500} aria-label={`Source quote for row ${index + 1}`} className={inputClass} value={row.source_excerpt} onChange={e => changeRow(index, "source_excerpt", e.target.value)} /></label>
          <label className="block text-sm">Period note<input required={row.cash_on_cash_pct === ""} maxLength={300} aria-label={`Period note for row ${index + 1}`} className={inputClass} value={row.note} onChange={e => changeRow(index, "note", e.target.value)} /></label>
          {rows.length > 1 && <Button type="button" variant="ghost" aria-label={`Remove row ${index + 1}`} onClick={() => setRows(rows.filter((_, i) => i !== index))}>Remove row</Button>}
        </fieldset>
      ))}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={rows.length >= 50 || saving} onClick={() => setRows([...rows, blankRow(Math.min(50, Number(rows.at(-1)?.year || 0) + 1))])}>Add year</Button>
        <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save reviewed schedule"}</Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>Cancel</Button>
      </div>
    </form>
  );
}
