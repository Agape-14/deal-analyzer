"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import type { AnalysisFact, DealDetail } from "@/lib/types";
import { fmtMoney, fmtPct, fmtMultiple } from "@/lib/utils";

export function factValue(fact?: AnalysisFact, reported = false): string {
  if (!fact || fact.value == null || (!reported && !["checked", "calculated", "manual"].includes(fact.state))) return "Awaiting evidence";
  const v = fact.value;
  if (Array.isArray(v)) return v.map(t => `${t.threshold}% hurdle: ${t.lp_split}% LP / ${t.gp_split}% GP`).join("; ");
  if (typeof v === "string") return v;
  if (fact.identity.unit === "currency") return fmtMoney(v);
  if (fact.identity.unit === "percent") return fmtPct(v);
  if (fact.identity.unit === "multiple") return fmtMultiple(v);
  if (["years", "months"].includes(fact.identity.unit)) return `${v} ${fact.identity.unit}`;
  return v.toLocaleString();
}

export function FactEvidence({ fact }: { fact?: AnalysisFact }) {
  if (!fact) return null;
  return <details className="mt-2 text-xs text-muted-foreground">
    <summary className="cursor-pointer">Evidence · {fact.state === "manual" ? "Analyst resolved" : fact.state}</summary>
    <div className="mt-2 space-y-2 leading-relaxed">
      {fact.reason && <p>{fact.reason}</p>}
      {fact.formula && <p>Calculated: {fact.formula}</p>}
      {fact.dependencies.length > 0 && <p>Inputs: {fact.dependencies.map(p => p.split(".").pop()?.replaceAll("_", " ")).join(", ")}</p>}
      {fact.evidence.map((e, i) => <div key={`${e.document_id}-${i}`}>
        <a className="underline" href={`/api/deals/documents/${e.document_id}/file${e.page ? `#page=${e.page}` : ""}`} target="_blank" rel="noreferrer">{e.document_name}{e.page ? ` · page ${e.page}` : ""}{e.sheet ? ` · ${e.sheet} ${e.cell ?? ""}` : ""}</a>
        {e.excerpt && <p className="mt-1 whitespace-pre-wrap">{e.excerpt}</p>}
      </div>)}
      {fact.alternatives.length > 0 && <p>Source alternatives: {fact.alternatives.map(v => typeof v === "object" ? JSON.stringify(v) : String(v)).join("; ")}</p>}
    </div>
  </details>;
}

export function AcceptedSummary({ deal }: { deal: DealDetail }) {
  const analysis = deal.analysis;
  if (!analysis) return <Card className="p-6">Analysis is unavailable. Reload after document review completes.</Card>;
  const facts = analysis.facts;
  const paths = ["deal_structure.total_project_cost", "deal_structure.total_equity_required", "deal_structure.debt_amount", "deal_structure.minimum_investment", "deal_structure.hold_period_years", "project_details.unit_count", "financial_projections.stabilized_noi", "underwriting_checks.dscr"];
  const cautions = (deal.metrics.validation_flags ?? []).filter(f => ["red", "yellow"].includes(f.severity) && !/data (integrity|conflict)|staleness/i.test(f.category));
  return <div className="space-y-6">
    <Card className="p-5 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><h2 className="text-lg font-semibold">One reviewed view of the deal</h2>
          <p className="mt-1 text-sm text-muted-foreground">{analysis.primary_strategy === "unknown" ? "Strategy needs clarification" : `Primary strategy: ${analysis.primary_strategy.replaceAll("_", " ")}`}{analysis.investor_class !== "unspecified" ? ` · ${analysis.investor_class}` : ""}</p>
        </div>
        <Link href={`/deals/${deal.id}?tab=questions`} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">{analysis.questions.length ? `${analysis.questions.length} question${analysis.questions.length === 1 ? "" : "s"}` : "No material questions"}</Link>
      </div>
      <p className="mt-4 text-sm text-muted-foreground">{analysis.coverage.accepted} of {analysis.coverage.total} recognized facts accepted: {analysis.coverage.checked} source checked, {analysis.coverage.calculated} calculated, {analysis.coverage.manual} analyst resolved. This describes evidence coverage, not investment quality.</p>
      <p className="mt-2 text-xs text-muted-foreground">{analysis.version ? `Analysis revision ${analysis.version}` : "Preview of existing data"}{analysis.created_at ? ` · ${new Date(analysis.created_at).toLocaleString()}` : ""}. Missing or disputed facts remain withheld.</p>
    </Card>
    <Card className="p-5 md:p-6"><h2 className="text-lg font-semibold">Capital, terms and operations</h2>
      <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">{paths.map(path => {
        const fact = facts[path];
        return <div key={path}><div className="text-xs text-muted-foreground">{fact?.label ?? path.split(".").pop()?.replaceAll("_", " ")}</div><div className="mt-1 text-lg font-semibold">{factValue(fact)}</div><FactEvidence fact={fact} /></div>;
      })}</div>
    </Card>
    {cautions.length > 0 && <Card className="p-5 md:p-6"><h2 className="text-lg font-semibold">Investment considerations</h2><p className="mt-1 text-sm text-muted-foreground">These inform your decision and do not require confirmation clicks.</p><ul className="mt-4 space-y-3 text-sm">{cautions.map((f, i) => <li key={i}><strong>{f.category}:</strong> {f.message}</li>)}</ul></Card>}
    <p className="text-sm text-muted-foreground">Upload missing or newer evidence in <Link className="underline" href={`/deals/${deal.id}?tab=documents`}>Documents</Link>. Reported values, optional context, projections and audit details remain under Analysis.</p>
  </div>;
}
