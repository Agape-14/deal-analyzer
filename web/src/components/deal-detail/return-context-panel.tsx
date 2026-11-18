"use client";

import { useState, type FormEvent } from "react";
import { returnContext } from "@/components/compare/comparison-context";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import type { AnalysisFact, DealDetail, DealDocument } from "@/lib/types";
import { fmtMultiple, fmtPct } from "@/lib/utils";
import { EvidenceViewer } from "./evidence-viewer";

const returnMetrics = [
  { key: "target_irr", pathKey: "target_irr_path", label: "Target IRR", format: fmtPct },
  { key: "target_equity_multiple", pathKey: "target_equity_multiple_path", label: "Equity multiple", format: fmtMultiple },
  { key: "cash_on_cash", pathKey: "cash_on_cash_path", label: "Cash-on-cash", format: fmtPct },
] as const;

const labelClass = "block text-xs font-medium text-muted-foreground";
const fieldClass = "mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground";
type Scenario = "hold" | "sale" | "unspecified";
type Action = "scope" | "withhold";

export function ReturnContextPanel({ deal }: { deal: DealDetail }) {
  const { isAnalyst } = useCurrentUser();
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const analysis = deal.analysis;
  if (!analysis) return null;

  const rows = returnMetrics.flatMap(({ key, pathKey, label, format }) => {
    const value = analysis.returns[key];
    const path = analysis.returns[pathKey];
    const fact = path ? analysis.facts[path] : undefined;
    return typeof value === "number" && fact ? [{ fact, label, value: format(value) }] : [];
  });
  if (!rows.length) return null;

  const documents = deal.documents.filter(doc => doc.has_text
    && doc.included_in_review !== false
    && (!doc.source_role || doc.source_role === "active"));

  return (
    <Card className="p-5 md:p-6">
      <h2 className="text-lg font-semibold">Published returns</h2>
      <ul className="mt-3 divide-y divide-border">
        {rows.map(({ fact, label, value }) => (
          <li key={fact.path} className="py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm font-medium">{label}</span>
                  <span className="text-base font-semibold">{value}</span>
                </div>
                <p className="mt-1 break-words text-xs text-muted-foreground">{returnContext(fact)}</p>
                {fact.evidence.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 break-words text-xs">
                    {fact.evidence.map((source, index) => (
                      <EvidenceViewer key={index} source={source} />
                    ))}
                  </div>
                )}
              </div>
              {isAnalyst && !!deal.revision && !editingPath && (
                <Button type="button" variant="outline" size="sm" onClick={() => setEditingPath(fact.path)}>
                  Review return
                </Button>
              )}
            </div>
            {isAnalyst && !!deal.revision && editingPath === fact.path && (
              <ReturnContextForm
                dealId={deal.id}
                revision={deal.revision}
                fact={fact}
                label={label}
                documents={documents}
                onCancel={() => setEditingPath(null)}
              />
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ReturnContextForm({ dealId, revision, fact, label, documents, onCancel }: {
  dealId: number;
  revision: number;
  fact: AnalysisFact;
  label: string;
  documents: DealDocument[];
  onCancel: () => void;
}) {
  const currentEvidence = fact.evidence.filter(source => documents.some(doc => doc.id === source.document_id));
  const priorEvidence = currentEvidence.find(source => source.page || (source.sheet && source.cell)) ?? currentEvidence[0];
  const identity = fact.identity;
  const [expectedRevision] = useState(revision);
  const [action, setAction] = useState<Action>(documents.length ? "scope" : "withhold");
  const [scenario, setScenario] = useState<Scenario>(
    identity.scenario === "hold" || identity.scenario === "sale" ? identity.scenario : "unspecified",
  );
  const [investorClass, setInvestorClass] = useState(identity.investor_class === "unspecified" ? "" : identity.investor_class);
  const [basis, setBasis] = useState(identity.basis === "unspecified" ? "" : identity.basis);
  const [period, setPeriod] = useState(identity.period === "unspecified" ? "" : identity.period);
  const [documentId, setDocumentId] = useState(String(priorEvidence?.document_id ?? (documents.length === 1 ? documents[0].id : "")));
  const [page, setPage] = useState(String(priorEvidence?.page ?? ""));
  const [sheet, setSheet] = useState(priorEvidence?.sheet ?? "");
  const [cell, setCell] = useState(priorEvidence?.cell ?? "");
  const [quote, setQuote] = useState(priorEvidence?.excerpt ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const document = documents.find(doc => String(doc.id) === documentId);
  const isPdf = document?.filename.toLowerCase().endsWith(".pdf");
  const citation = isPdf ? { source_page: Number(page) } : { source_sheet: sheet.trim(), source_cell: cell.trim() };
  const hasLocator = isPdf ? Number.isInteger(Number(page)) && Number(page) > 0 : !!sheet.trim() && /^[A-Z]{1,3}[1-9]\d*$/.test(cell);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (action === "scope" && (!document || !hasLocator || quote.trim().length < 8)) {
      setError("Choose a source and provide its location and exact quote.");
      return;
    }
    if (action === "withhold" && reason.trim().length < 3) {
      setError("Enter a reason for withholding this return.");
      return;
    }

    setBusy(true);
    try {
      await api.put("/api/deals/" + dealId + "/analysis/return-context", {
        expected_revision: expectedRevision,
        path: fact.path,
        ...(action === "scope" && document ? {
          action,
          scenario,
          investor_class: investorClass.trim() || undefined,
          basis: basis.trim() || undefined,
          period: period.trim() || undefined,
          source_doc_id: document.id,
          ...citation,
          source_excerpt: quote.trim(),
        } : { action: "withhold", reason: reason.trim() }),
      });
      window.location.reload();
    } catch (err) {
      const detail = (err as { detail?: unknown })?.detail;
      setError(typeof detail === "string" ? detail : "The return decision could not be saved. Check the fields and try again.");
      setBusy(false);
    }
  }

  return (
    <form className="mt-3 rounded-lg border border-border bg-muted/20 p-4" aria-label={"Review " + label} onSubmit={save}>
      <fieldset className="space-y-3" disabled={busy}>
        {documents.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {([{ key: "scope", label: "Set context" }, { key: "withhold", label: "Withhold" }] as const).map(choice => (
              <Button key={choice.key} type="button" size="sm" variant={action === choice.key ? "secondary" : "ghost"}
                aria-pressed={action === choice.key} onClick={() => { setAction(choice.key); setError(""); }}>
                {choice.label}
              </Button>
            ))}
          </div>
        )}
        {action === "scope" ? (
          <>
            <p className="text-xs text-muted-foreground">Enter the details the source supports. Leave unknown fields blank.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className={labelClass}>Scenario
                <select className={fieldClass} value={scenario} onChange={e => setScenario(e.target.value as Scenario)}>
                  <option value="unspecified">Unspecified</option>
                  <option value="hold">Hold</option>
                  <option value="sale">Sale</option>
                </select>
              </label>
              <label className={labelClass}>Investor class
                <Input className="mt-1" maxLength={100} value={investorClass} onChange={e => setInvestorClass(e.target.value)} />
              </label>
              <label className={labelClass}>Calculation basis
                <Input className="mt-1" maxLength={100} placeholder="e.g. net" value={basis} onChange={e => setBasis(e.target.value)} />
              </label>
              <label className={labelClass}>Period
                <Input className="mt-1" maxLength={100} value={period} onChange={e => setPeriod(e.target.value)} />
              </label>
              <label className={labelClass}>Source document
                <select className={fieldClass} required value={documentId} onChange={e => {
                  setDocumentId(e.target.value);
                  setPage("");
                  setSheet("");
                  setCell("");
                  setQuote("");
                }}>
                  <option value="">Select a current source</option>
                  {documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}
                </select>
              </label>
              {document && (isPdf ? (
                <label className={labelClass}>PDF page
                  <Input className="mt-1" type="number" min={1} max={document.page_count || undefined} required value={page} onChange={e => setPage(e.target.value)} />
                </label>
              ) : (
                <>
                  <label className={labelClass}>Sheet
                    <Input className="mt-1" required maxLength={200} value={sheet} onChange={e => setSheet(e.target.value)} />
                  </label>
                  <label className={labelClass}>Value cell
                    <Input className="mt-1" required pattern="[A-Za-z]{1,3}[1-9][0-9]{0,6}" value={cell} onChange={e => setCell(e.target.value.toUpperCase())} />
                  </label>
                </>
              ))}
            </div>
            {document && hasLocator && <div className="break-words text-xs">
              <EvidenceViewer source={{ document_id: document.id, document_name: document.filename, page: isPdf ? Number(page) : null, sheet: isPdf ? null : sheet, cell: isPdf ? null : cell }} />
            </div>}
            <label className={labelClass}>Exact supporting quote
              <textarea className={fieldClass} rows={2} required minLength={8} maxLength={1500} value={quote} onChange={e => setQuote(e.target.value)} />
            </label>
          </>
        ) : (
          <label className={labelClass}>Reason for withholding
            <textarea className={fieldClass} rows={2} required minLength={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} />
            <span className="mt-1 block">The return is removed from published figures. The decision is recorded in Analysis history.</span>
          </label>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" variant={action === "withhold" ? "destructive" : "default"}>
            {busy ? "Saving…" : action === "scope" ? "Save source-backed context" : "Withhold return"}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </fieldset>
    </form>
  );
}
