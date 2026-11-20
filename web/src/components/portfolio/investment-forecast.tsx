"use client";

import type { Investment } from "@/lib/types";
import { fmtDate } from "@/lib/utils";
import { EvidenceViewer } from "@/components/deal-detail/evidence-viewer";
import { ReturnScheduleTable } from "@/components/deal-detail/return-schedule-panel";

const TERM_LABELS: Record<string, string> = { investment_class: "Investor class", preferred_return: "Preferred return", projected_irr: "Projected IRR", projected_equity_multiple: "Projected multiple", projected_cash_on_cash: "Projected cash-on-cash", hold_period_years: "Hold period" };
function termValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const unit = key === "projected_equity_multiple" ? "×" : key === "hold_period_years" ? " years" : key === "investment_class" ? "" : "%";
  return `${value}${unit}`;
}

export function InvestmentForecast({ investment }: { investment: Investment }) {
  const snapshot = investment.forecast_snapshot;
  const overrides = Object.entries(investment.terms_overrides ?? {});
  return <details className="mt-4 border-t border-border/50 pt-3 text-xs" data-testid="investment-forecast">
    <summary className="cursor-pointer font-medium">Forecast & review history</summary>
    <p className="my-3 text-muted-foreground">Projections describe underwriting. Realized performance uses recorded payments and dated valuations.</p>
    <dl className="grid grid-cols-2 gap-2">{Object.entries(TERM_LABELS).map(([key, label]) => <div key={key}><dt className="text-muted-foreground">{label}{investment.terms_overrides?.[key] ? " · manual" : ""}</dt><dd className="mt-0.5">{termValue(key, investment[key as keyof Investment])}</dd></div>)}</dl>
    {snapshot ? <div className="mt-4 space-y-3">
      <h4 className="font-semibold">Accepted forecast at entry</h4>
      <p className="text-muted-foreground">Saved {fmtDate(snapshot.captured_at)} · deal revision {snapshot.deal_revision} · analysis revision {snapshot.analysis_version} · {snapshot.primary_strategy ?? "Unspecified strategy"} · {String(snapshot.terms.investment_class || "Unspecified class")}</p>
      <p className="text-muted-foreground">This baseline stays as captured when the deal changes. Its saved quotes and source hashes identify the reviewed version.</p>
      <dl className="grid grid-cols-2 gap-2">{Object.entries(snapshot.terms).map(([key, value]) => <div key={key}><dt className="text-muted-foreground">{TERM_LABELS[key] ?? key}</dt><dd>{termValue(key, value)}</dd></div>)}</dl>
      {Object.entries(snapshot.facts).map(([path, fact]) => <div key={path} className="space-y-1"><p className="font-medium">{fact.label}</p><p className="text-muted-foreground">{[fact.identity.scenario, fact.identity.investor_class, fact.identity.basis, fact.identity.period].filter(value => value && value !== "unspecified").join(" · ") || "Context unspecified"}{fact.state === "manual" ? " · analyst resolved" : ""}</p>{fact.evidence.map((source, index) => <div key={index}><EvidenceViewer source={source} />{source.excerpt && <blockquote className="mt-1 whitespace-pre-wrap border-l-2 pl-2 text-muted-foreground">{source.excerpt}</blockquote>}</div>)}</div>)}
      {snapshot.return_schedule && <div className="space-y-3"><p className="font-medium">Original approved hold schedule</p>{snapshot.return_schedule.investor_class !== investment.investment_class && <p className="text-warning">This saved schedule describes {snapshot.return_schedule.investor_class}. The position now records another class.</p>}<ReturnScheduleTable schedule={snapshot.return_schedule} /></div>}
      <details className="text-muted-foreground"><summary className="cursor-pointer">Snapshot identifiers</summary><p className="mt-2 break-all">Analysis {snapshot.analysis_input_hash}</p><p className="break-all">App commit {snapshot.app_commit}</p></details>
    </div> : <p className="mt-3 text-muted-foreground">No forecast snapshot was captured for this position. Existing stored projections remain available.</p>}
    {overrides.length > 0 && <div className="mt-4 space-y-2"><h4 className="font-semibold">Manual term changes</h4>{overrides.map(([field, entry]) => <details key={field}><summary className="cursor-pointer">{TERM_LABELS[field] ?? field} · {termValue(field, entry.value)}</summary><p className="mt-1 text-muted-foreground">Original baseline {termValue(field, entry.baseline_value)}</p><ul className="mt-1 space-y-1">{entry.history.map((event, index) => <li key={index}>{fmtDate(event.recorded_at)} · {event.investor_class && `${event.investor_class} · `}{termValue(field, event.previous_value)} → {termValue(field, event.value)}{event.reason && ` · ${event.reason}`}</li>)}</ul></details>)}</div>}
  </details>;
}
