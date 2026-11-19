import type { ReturnCrosscheck } from "@/lib/types";
import { fmtMultiple, fmtPct } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { EvidenceViewer } from "./evidence-viewer";

export function ReturnCrosscheckDetails({ check }: { check: ReturnCrosscheck }) {
  const iso = /^[A-Z]{3}$/.test(check.currency);
  const money = new Intl.NumberFormat("en-US", iso ? {
    style: "currency", currency: check.currency, maximumFractionDigits: 2,
  } : { maximumFractionDigits: 2 });
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {[check.investor_class, check.scenario === "sale" ? "Sale case" : "Hold case", check.basis].filter(Boolean).join(" · ")}
      </p>
      {check.status === "needs_review" ? (
        <p className="text-sm font-medium text-warning">Source version changed. Recheck the cash flows against the current document.</p>
      ) : (
        <dl className="flex flex-wrap gap-x-8 gap-y-3">
          <div>
            <dt className="text-xs text-muted-foreground">Annual-period IRR</dt>
            <dd className="font-semibold tabular-nums">{check.annual_irr_pct == null ? "Unavailable" : fmtPct(check.annual_irr_pct)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Cash-flow multiple</dt>
            <dd className="font-semibold tabular-nums">{check.cash_flow_multiple == null ? "Unavailable" : fmtMultiple(check.cash_flow_multiple)}</dd>
          </div>
        </dl>
      )}
      <p className="text-xs text-muted-foreground">{check.calculation_basis}</p>
      {check.warnings.map(warning => <p key={warning} className="text-xs text-muted-foreground">{warning}</p>)}
      <details className="rounded-lg border border-border/70">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">Cited cash flows</summary>
        <div className="overflow-x-auto">
          <table aria-label="Cited annual cash flows" className="w-full min-w-[22rem] text-left text-xs">
            <thead className="border-y border-border/70 bg-muted/30">
              <tr><th scope="col" className="px-3 py-2">Period</th><th scope="col" className="px-3 py-2">Amount</th><th scope="col" className="px-3 py-2">Source and context</th></tr>
            </thead>
            <tbody>
              {check.rows.map(row => (
                <tr key={row.year} className="border-b border-border/50 last:border-0">
                  <th scope="row" className="px-3 py-2 font-medium">{row.label ?? row.year}</th>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums">
                    {iso ? money.format(row.amount) : `${row.amount < 0 ? "−" : ""}${check.currency}${money.format(Math.abs(row.amount))}`}
                  </td>
                  <td className="space-y-1 px-3 py-2 text-muted-foreground">
                    {(row.flow_scope_label || row.date_label) && <p>{[row.flow_scope_label, row.date_label].filter(Boolean).join(" · ")}</p>}
                    {[...(row.evidence ?? []), ...(row.event_evidence ?? [])].map((source, index) => (
                      <EvidenceViewer key={`${source.document_id}-${source.page}-${index}`} source={source} />
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      {!!check.evidence.length && <div className="flex flex-wrap gap-2">
        {check.evidence.map((source, index) => <EvidenceViewer key={`${source.document_id}-${index}`} source={source} />)}
      </div>}
    </div>
  );
}

export function ReturnCrosscheckPanel({ check }: { check?: ReturnCrosscheck | null }) {
  if (!check) return null;
  return (
    <Card id="return-crosscheck" className="scroll-mt-20 space-y-3 p-5 md:p-6">
      <h2 className="text-lg font-semibold">PDF cash-flow check</h2>
      <ReturnCrosscheckDetails check={check} />
    </Card>
  );
}
