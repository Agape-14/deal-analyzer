"use client";

import { AlertTriangle, Calculator, CheckCircle2, FileText, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FieldReviewAction } from "@/components/deal-detail/field-review-action";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DataQualityGate, DealDetail, FieldProvenance, ValidationFlag } from "@/lib/types";

type ReviewItem = {
  key: string;
  priority: number;
  kind: "math" | "flag" | "source";
  severity: "red" | "yellow";
  title: string;
  detail: string;
  path?: string;
  value?: unknown;
  provenance?: FieldProvenance;
  source?: string;
};

const REVIEW_LIMIT = 3;

const REVIEW_FIELDS = [
  { path: "target_returns.net_irr", label: "Target IRR", format: "pct" },
  { path: "target_returns.target_irr", label: "Target IRR alias", format: "pct" },
  { path: "target_returns.net_equity_multiple", label: "Equity multiple", format: "multiple" },
  { path: "target_returns.target_equity_multiple", label: "Equity multiple alias", format: "multiple" },
  { path: "target_returns.target_cash_on_cash", label: "Cash-on-cash", format: "pct" },
  { path: "target_returns.distribution_yield", label: "Distribution yield", format: "pct" },
  { path: "deal_structure.minimum_investment", label: "Minimum investment", format: "money" },
  { path: "deal_structure.total_project_cost", label: "Total project cost", format: "money" },
  { path: "deal_structure.total_equity_required", label: "Equity required", format: "money" },
  { path: "deal_structure.debt_amount", label: "Debt amount", format: "money" },
  { path: "deal_structure.ltv", label: "LTV", format: "pct" },
  { path: "financial_projections.stabilized_noi", label: "Stabilized NOI", format: "money" },
  { path: "financial_projections.avg_rent_per_unit", label: "Average rent", format: "money" },
  { path: "financial_projections.occupancy_assumption", label: "Occupancy", format: "pct" },
  { path: "project_details.unit_count", label: "Unit count", format: "integer" },
] as const;

export function ReviewQueue({ deal }: { deal: DealDetail }) {
  const items = buildReviewItems(deal);
  const visible = items.slice(0, REVIEW_LIMIT);
  const hiddenCount = Math.max(0, items.length - visible.length);

  if (items.length === 0) {
    return (
      <Card elevated className="p-6">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-success/15 text-success ring-1 ring-success/30">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold tracking-tight">Review queue</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">No action items. This deal is ready for decision review.</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card elevated className="p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-destructive/15 text-destructive ring-1 ring-destructive/30">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold tracking-tight">Review queue</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {items.length} item{items.length === 1 ? "" : "s"} need review before this deal can be trusted.
            </p>
          </div>
        </div>
        {hiddenCount > 0 && (
          <a href="#technical-details" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
            {hiddenCount} more in technical details
          </a>
        )}
      </div>

      <div className="mt-5 space-y-3">
        {visible.map((item, index) => (
          <ReviewRow key={item.key} item={item} index={index} dealId={deal.id} />
        ))}
      </div>
    </Card>
  );
}

function ReviewRow({ item, index, dealId }: { item: ReviewItem; index: number; dealId: number }) {
  const Icon = item.kind === "math" ? Calculator : item.kind === "source" ? FileText : AlertTriangle;
  return (
    <div className="grid gap-3 rounded-lg border border-border/70 bg-card/40 p-4 md:grid-cols-[auto_1fr_auto] md:items-center">
      <div className={cn(
        "flex h-8 w-8 items-center justify-center rounded-md text-xs font-semibold ring-1",
        item.severity === "red"
          ? "bg-destructive/15 text-destructive ring-destructive/30"
          : "bg-warning/15 text-warning ring-warning/30",
      )}>
        {index + 1}
      </div>

      <div className="min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Icon className={cn("h-4 w-4", item.severity === "red" ? "text-destructive" : "text-warning")} />
          <div className="font-semibold tracking-tight">{item.title}</div>
          {item.path && (
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground ring-1 ring-border/70">
              {item.path}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.detail}</p>
        {(item.value !== undefined || item.source) && (
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            {item.value !== undefined && <span>Current: <span className="text-foreground">{formatReviewValue(item.value, item.path)}</span></span>}
            {item.source && <span>Source: <span className="text-foreground">{item.source}</span></span>}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 md:justify-end">
        {item.path && item.provenance ? (
          <FieldReviewAction dealId={dealId} path={item.path} value={item.value} provenance={item.provenance} />
        ) : null}
        <Button size="sm" variant="outline" asChild>
          <a href={item.kind === "math" ? "#technical-details" : "#source-citations"}>Review source</a>
        </Button>
      </div>
    </div>
  );
}

function buildReviewItems(deal: DealDetail): ReviewItem[] {
  const metrics = deal.metrics ?? {};
  const gate = deal.scores?.data_quality ?? metrics._data_quality;
  const provenance = metrics._provenance ?? {};
  const flags = metrics.validation_flags ?? [];
  const items: ReviewItem[] = [];

  items.push(...mathItems(gate));
  items.push(...flagItems(flags, metrics, provenance));
  items.push(...sourceItems(metrics, provenance));

  return dedupeItems(items)
    .sort((a, b) => b.priority - a.priority)
    .slice(0, 12);
}

function mathItems(gate?: DataQualityGate): ReviewItem[] {
  const blocking = gate?.math_summary?.blocking ?? [];
  return blocking.map((check, index) => ({
    key: `math:${check.check ?? index}`,
    priority: 100 - index,
    kind: "math" as const,
    severity: "red" as const,
    title: check.check || "Math check failed",
    detail: [check.difference, check.formula].filter(Boolean).join(" - ") || "A deterministic calculation does not match the extracted deal values.",
  }));
}

function flagItems(
  flags: ValidationFlag[],
  metrics: DealDetail["metrics"],
  provenance: Record<string, FieldProvenance>,
): ReviewItem[] {
  return flags
    .filter((flag) => ["red", "yellow"].includes(String(flag.severity).toLowerCase()))
    .map((flag, index) => {
      const path = extractBestPath(flag.message);
      return {
        key: `flag:${flag.category}:${path ?? flag.message}`,
        priority: flag.severity === "red" ? 80 - index : 45 - index,
        kind: "flag" as const,
        severity: flag.severity === "red" ? "red" as const : "yellow" as const,
        title: flagTitle(flag, path),
        detail: simplifyMessage(flag.message),
        path,
        value: path ? getPath(metrics, path) : undefined,
        provenance: path ? provenance[path] : undefined,
        source: path ? sourceLabel(provenance[path]) : undefined,
      };
    });
}

function sourceItems(metrics: DealDetail["metrics"], provenance: Record<string, FieldProvenance>): ReviewItem[] {
  const out: ReviewItem[] = [];
  for (const field of REVIEW_FIELDS) {
    const prov = provenance[field.path];
    const value = getPath(metrics, field.path);
    if (!prov || prov.locked) continue;
    const status = String(prov.status ?? "");
    const confidence = typeof prov.confidence === "number" ? prov.confidence : null;
    const conflictCount = Array.isArray(prov.conflict) ? prov.conflict.length : 0;
    const needsReview = conflictCount > 1 || ["wrong", "missing", "unverifiable", "stale"].includes(status) || (confidence !== null && confidence < 85);
    if (!needsReview) continue;
    out.push({
      key: `source:${field.path}`,
      priority: conflictCount > 1 || status === "wrong" ? 75 : confidence !== null ? 40 - confidence / 10 : 35,
      kind: "source",
      severity: conflictCount > 1 || status === "wrong" || status === "missing" ? "red" : "yellow",
      title: `${field.label} needs review`,
      detail: sourceDetail(prov),
      path: field.path,
      value,
      provenance: prov,
      source: sourceLabel(prov),
    });
  }
  return out;
}

function dedupeItems(items: ReviewItem[]): ReviewItem[] {
  const byKey = new Map<string, ReviewItem>();
  for (const item of items) {
    const key = item.path ?? item.key;
    const existing = byKey.get(key);
    if (!existing || item.priority > existing.priority) byKey.set(key, item);
  }
  return Array.from(byKey.values());
}

function extractBestPath(message: string): string | undefined {
  const matches = message.match(/[a-z_]+\.[a-z_]+/g) ?? [];
  const preferred = matches.find((path) => path.includes("net_")) ?? matches[0];
  return preferred;
}

function flagTitle(flag: ValidationFlag, path?: string): string {
  if (path) return `${humanizePath(path)} needs review`;
  return `${flag.category} needs review`;
}

function simplifyMessage(message: string): string {
  if (message.length <= 190) return message;
  return `${message.slice(0, 187)}...`;
}

function sourceDetail(provenance: FieldProvenance): string {
  if (Array.isArray(provenance.conflict) && provenance.conflict.length > 1) return "Documents disagree. Pick the correct source value and lock it.";
  if (provenance.status === "wrong") return "Verification challenged this value. Confirm the correction or edit the field.";
  if (provenance.status === "missing") return "This required field is missing from the extracted data.";
  if (provenance.status === "unverifiable") return "The verifier could not tie this value back to a source document.";
  if (typeof provenance.confidence === "number") return `Confidence is ${provenance.confidence}%, below the 85% review threshold.`;
  return "This value still needs human review before it can be trusted.";
}

function sourceLabel(provenance?: FieldProvenance): string | undefined {
  if (!provenance?.source_doc_name) return undefined;
  return `${provenance.source_doc_name}${provenance.source_page ? ` p.${provenance.source_page}` : ""}`;
}

function getPath(data: unknown, path?: string): unknown {
  if (!path) return undefined;
  let cur = data;
  for (const part of path.split(".")) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function formatReviewValue(value: unknown, path?: string): string {
  if (value == null || value === "") return "missing";
  const n = typeof value === "number" ? value : typeof value === "string" && !Number.isNaN(Number(value)) ? Number(value) : null;
  if (n == null) return String(value);
  const field = REVIEW_FIELDS.find((f) => f.path === path);
  switch (field?.format) {
    case "pct":
      return fmtPct(n, 1);
    case "money":
      return fmtMoney(n);
    case "multiple":
      return fmtMultiple(n);
    case "integer":
      return Math.round(n).toLocaleString();
    default:
      return String(value);
  }
}

function humanizePath(path: string): string {
  const [, field = path] = path.split(".");
  return field.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
