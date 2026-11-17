"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import { financingKinds, type FinancingAnalysis, type FinancingKind } from "@/lib/financing-measures";
import type { DealDetail, DealDocument } from "@/lib/types";
import { EvidenceViewer } from "./evidence-viewer";

type EditableMeasure = {
  kind: FinancingKind;
  amount: string;
  documentId: string;
  page: string;
  sheet: string;
  cell: string;
  quote: string;
  note: string;
};

const kinds = Object.keys(financingKinds) as FinancingKind[];
const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
});
const fieldClass = "mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const labelClass = "block text-xs font-medium text-muted-foreground";

function blankMeasure(kind: FinancingKind): EditableMeasure {
  return { kind, amount: "", documentId: "", page: "", sheet: "", cell: "", quote: "", note: "" };
}

function isPdf(document?: DealDocument) {
  return !!document?.filename.toLowerCase().endsWith(".pdf");
}

export function FinancingMeasuresPanel({ deal, financing, debtAmount }: {
  deal: DealDetail;
  financing?: FinancingAnalysis;
  debtAmount: number | null;
}) {
  const { isAnalyst } = useCurrentUser();
  const measures = financing?.measures ?? [];
  const documents = deal.documents.filter(document => document.has_text && document.included_in_review !== false && (!document.source_role || document.source_role === "active"));
  const editable = isAnalyst && !!deal.revision && documents.length > 0;
  const [draft, setDraft] = React.useState<EditableMeasure[] | null>(null);
  const [primary, setPrimary] = React.useState<FinancingKind | "">("");
  const [addKind, setAddKind] = React.useState<FinancingKind | "">("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  if (!editable && !measures.length) return null;

  function edit() {
    setError("");
    setAddKind("");
    setPrimary(financing?.debt_amount_kind ?? "");
    setDraft(measures.map(row => ({
      kind: row.kind,
      amount: String(row.amount),
      documentId: String(row.citation.source_doc_id),
      page: row.citation.source_page ? String(row.citation.source_page) : "",
      sheet: row.citation.source_sheet ?? "",
      cell: row.citation.source_cell ?? "",
      quote: row.citation.source_excerpt,
      note: row.note,
    })));
  }

  function update(kind: FinancingKind, change: Partial<EditableMeasure>) {
    setDraft(current => current?.map(row => row.kind === kind ? { ...row, ...change } : row) ?? null);
    if ("amount" in change && primary === kind) setPrimary("");
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;

    setError("");
    setBusy(true);
    try {
      const request = draft.map(row => {
        const document = documents.find(item => String(item.id) === row.documentId);
        if (!document) throw new Error("Choose a current source document for every measure.");
        return {
          kind: row.kind,
          amount: Number(row.amount),
          source_doc_id: document.id,
          ...(isPdf(document) ? { source_page: Number(row.page) } : { source_sheet: row.sheet, source_cell: row.cell }),
          source_excerpt: row.quote,
          note: row.note,
        };
      });
      await api.put(`/api/deals/${deal.id}/analysis/financing-measures`, {
        expected_revision: deal.revision,
        debt_amount_kind: primary || null,
        measures: request,
      });
      window.location.reload();
    } catch (err) {
      const detail = (err as { detail?: unknown })?.detail;
      setError(typeof detail === "string" ? detail : err instanceof Error ? err.message : "Check the amount and citation for each financing measure.");
      setBusy(false);
    }
  }

  const remaining = kinds.filter(kind => !draft?.some(row => row.kind === kind));
  const matching = draft?.filter(row => row.amount !== "" && debtAmount !== null && Number(row.amount) === debtAmount) ?? [];

  return <Card className="p-5 md:p-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">Construction financing</h2>
        {measures.length === 0 && <p className="mt-1 text-sm text-muted-foreground">Add quoted loan draws, balances, or commitments.</p>}
      </div>
      {editable && draft === null && <Button type="button" size="sm" variant="outline" onClick={edit}>Review financing measures</Button>}
    </div>
    {measures.length > 0 && <ul className="mt-3 divide-y divide-border">
      {measures.map(measure => <li key={measure.kind} className="py-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="font-medium">{measure.label}</span>
          <span className="tabular-nums">{measure.state === "checked" ? dollars.format(measure.amount) : "Source needs review"}</span>
        </div>
        {measure.state === "checked" && measure.note && <p className="mt-1 text-sm text-muted-foreground">{measure.note}</p>}
        {measure.evidence.map(source => <div key={source.document_id} className="mt-1 text-xs"><EvidenceViewer source={source} /></div>)}
      </li>)}
    </ul>}
    {editable && draft !== null && <form className="mt-4 space-y-4 border-t border-border pt-4" onSubmit={save}>
      <p className="text-sm text-muted-foreground">Quote the amount and its description from a current PDF page or spreadsheet cell.</p>
      <fieldset disabled={busy} className="space-y-4">
        {draft.map(row => {
          const document = documents.find(item => String(item.id) === row.documentId);
          return <fieldset key={row.kind} className="space-y-3 rounded-md border border-border p-3">
            <legend className="px-1 text-sm font-medium">{financingKinds[row.kind]}</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className={labelClass}>Amount (USD)<Input className="mt-1" type="number" step="0.01" min={0} max={10 ** 15} required value={row.amount} onChange={event => update(row.kind, { amount: event.target.value })} /></label>
              <label className={labelClass}>Source document
                <select className={fieldClass} required value={document ? row.documentId : ""} onChange={event => update(row.kind, { documentId: event.target.value, page: "", sheet: "", cell: "", quote: "" })}>
                  <option value="">Select a current source</option>
                  {documents.map(item => <option key={item.id} value={item.id}>{item.filename}</option>)}
                </select>
              </label>
              {isPdf(document) && <label className={labelClass}>PDF page<Input className="mt-1" type="number" min={1} max={document?.page_count || undefined} required value={row.page} onChange={event => update(row.kind, { page: event.target.value })} /></label>}
              {document && !isPdf(document) && <>
                <label className={labelClass}>Sheet<Input className="mt-1" required maxLength={200} value={row.sheet} onChange={event => update(row.kind, { sheet: event.target.value })} /></label>
                <label className={labelClass}>Value cell<Input className="mt-1" required pattern="[A-Za-z]{1,3}[1-9][0-9]{0,6}" value={row.cell} onChange={event => update(row.kind, { cell: event.target.value.toUpperCase() })} /></label>
              </>}
            </div>
            <label className={labelClass}>Supporting quote
              <textarea className={fieldClass} rows={2} minLength={8} maxLength={1000} required value={row.quote} onChange={event => update(row.kind, { quote: event.target.value })} />
            </label>
            <label className={labelClass}>Note (optional)<Input className="mt-1" maxLength={500} value={row.note} onChange={event => update(row.kind, { note: event.target.value })} /></label>
            <Button type="button" size="sm" variant="ghost" onClick={() => {
              setDraft(current => current?.filter(item => item.kind !== row.kind) ?? []);
              if (primary === row.kind) setPrimary("");
            }}>Remove {financingKinds[row.kind].toLowerCase()}</Button>
          </fieldset>;
        })}
        {remaining.length > 0 && <div className="flex flex-wrap items-end gap-2">
          <label className={labelClass}>Measure to add
            <select className={fieldClass} value={addKind} onChange={event => setAddKind(event.target.value as FinancingKind | "")}>
              <option value="">Choose a measure</option>
              {remaining.map(kind => <option key={kind} value={kind}>{financingKinds[kind]}</option>)}
            </select>
          </label>
          <Button type="button" size="sm" variant="outline" disabled={!addKind} onClick={() => {
            if (!addKind) return;
            setDraft(current => [...(current ?? []), blankMeasure(addKind)]);
            setAddKind("");
          }}>Add measure</Button>
        </div>}
        {matching.length > 0 && <label className={labelClass}>Label for accepted debt amount
          <select className={fieldClass} value={primary} onChange={event => setPrimary(event.target.value as FinancingKind | "")}>
            <option value="">Debt amount</option>
            {matching.map(row => <option key={row.kind} value={row.kind}>{financingKinds[row.kind]}</option>)}
          </select>
        </label>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={!draft.length && !measures.length}>{busy ? "Saving…" : "Save financing measures"}</Button>
          <Button type="button" variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
        </div>
      </fieldset>
    </form>}
  </Card>;
}
