"use client";

import * as React from "react";
import {
  AlertTriangle,
  Calculator,
  CheckCircle2,
  FileText,
  HelpCircle,
  Loader2,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ReviewQueueEmptyState, ReviewQueueHeader } from "@/components/deal-detail/review-queue-shell";
import { SourceDetailsDrawer } from "@/components/deal-detail/source-details-drawer";
import { api } from "@/lib/api";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";
import type { DataQualityGate, DealDetail, FieldProvenance, ValidationFlag } from "@/lib/types";

type ReviewArea = "Returns" | "Capital Stack" | "Debt" | "Construction" | "Sponsor" | "Market" | "Source" | "Math";
type Severity = "red" | "yellow";
type Metrics = NonNullable<DealDetail["metrics"]>;
type ReviewGate = Pick<DataQualityGate, "critical_fields" | "math_summary">;
type CriticalField = NonNullable<DataQualityGate["critical_fields"]>[number];
type FieldFormat = "pct" | "multiple" | "money" | "integer" | "text";

type ReviewInput = {
  path: string;
  label: string;
  format: FieldFormat;
  value: unknown;
  provenance?: FieldProvenance;
};

type ReviewItem = {
  key: string;
  priority: number;
  kind: "math" | "flag" | "source";
  area: ReviewArea;
  severity: Severity;
  title: string;
  detail: string;
  path?: string;
  value?: unknown;
  source?: string;
  provenance?: FieldProvenance;
  inputs?: ReviewInput[];
  confirmLabel?: string;
};

type MathCheck = { check?: string; difference?: string; formula?: string; message?: string };

const BAD_SOURCE_STATUSES = new Set(["wrong", "missing", "unverifiable", "stale", "math_failed"]);
const REVIEW_THRESHOLD = 70;

const FIELD_META: Record<string, { label: string; format: FieldFormat }> = {
  "target_returns.target_irr": { label: "Target IRR", format: "pct" },
  "target_returns.net_irr": { label: "Net IRR", format: "pct" },
  "target_returns.target_equity_multiple": { label: "Equity multiple", format: "multiple" },
  "target_returns.net_equity_multiple": { label: "Net equity multiple", format: "multiple" },
  "target_returns.target_cash_on_cash": { label: "Cash-on-cash", format: "pct" },
  "target_returns.distribution_yield": { label: "Distribution yield", format: "pct" },
  "deal_structure.minimum_investment": { label: "Minimum investment", format: "money" },
  "deal_structure.total_project_cost": { label: "Total project cost", format: "money" },
  "deal_structure.total_equity_required": { label: "Equity required", format: "money" },
  "deal_structure.preferred_equity_amount": { label: "Pref equity", format: "money" },
  "deal_structure.debt_amount": { label: "Debt", format: "money" },
  "deal_structure.interest_rate": { label: "Interest rate", format: "pct" },
  "deal_structure.ltv": { label: "LTV", format: "pct" },
  "deal_structure.hold_period_years": { label: "Hold period", format: "integer" },
  "deal_structure.investment_term_years": { label: "Investment term", format: "integer" },
  "deal_structure.preferred_return": { label: "Preferred return", format: "pct" },
  "deal_structure.gp_equity_coinvest_pct": { label: "GP co-invest", format: "pct" },
  "deal_structure.gp_cash_at_risk": { label: "GP cash at risk", format: "money" },
  "financial_projections.stabilized_noi": { label: "Stabilized NOI", format: "money" },
  "financial_projections.entry_cap_rate": { label: "Entry cap rate", format: "pct" },
  "financial_projections.exit_cap_rate": { label: "Exit cap rate", format: "pct" },
  "financial_projections.occupancy_assumption": { label: "Occupancy", format: "pct" },
  "financial_projections.rent_growth_assumption": { label: "Rent growth", format: "pct" },
  "financial_projections.revenue_per_unit": { label: "Revenue per unit", format: "money" },
  "construction_costs.hard_costs": { label: "Hard costs", format: "money" },
  "construction_costs.hard_costs_total": { label: "Hard costs total", format: "money" },
  "construction_costs.soft_costs": { label: "Soft costs", format: "money" },
  "construction_costs.soft_costs_total": { label: "Soft costs total", format: "money" },
  "construction_costs.land_cost": { label: "Land", format: "money" },
  "construction_costs.land_cost_total": { label: "Land total", format: "money" },
  "construction_costs.contingency": { label: "Contingency", format: "money" },
  "construction_costs.contingency_total": { label: "Contingency total", format: "money" },
  "underwriting_checks.dscr": { label: "DSCR", format: "multiple" },
  "underwriting_checks.yield_on_cost": { label: "Yield on cost", format: "pct" },
  "sponsor_evaluation.alignment_score": { label: "Alignment score", format: "integer" },
  "sponsor_evaluation.sponsor_skin_in_game": { label: "Sponsor skin in game", format: "text" },
};

const MATH_CONFIGS: Array<{ test: (name: string) => boolean; area: ReviewArea; primary: string; inputs: string[] }> = [
  {
    test: (name) => name.includes("dscr") || name.includes("debt service"),
    area: "Debt",
    primary: "underwriting_checks.dscr",
    inputs: ["underwriting_checks.dscr", "financial_projections.stabilized_noi", "deal_structure.debt_amount", "deal_structure.interest_rate"],
  },
  {
    test: (name) => name.includes("ltv"),
    area: "Debt",
    primary: "deal_structure.ltv",
    inputs: ["deal_structure.ltv", "deal_structure.debt_amount", "deal_structure.total_project_cost"],
  },
  {
    test: (name) => name.includes("total project cost") && name.includes("equity"),
    area: "Capital Stack",
    primary: "deal_structure.total_project_cost",
    inputs: ["deal_structure.total_project_cost", "deal_structure.total_equity_required", "deal_structure.debt_amount"],
  },
  {
    test: (name) => name.includes("hard") && name.includes("soft") && name.includes("land"),
    area: "Construction",
    primary: "deal_structure.total_project_cost",
    inputs: [
      "construction_costs.hard_costs",
      "construction_costs.hard_costs_total",
      "construction_costs.soft_costs",
      "construction_costs.soft_costs_total",
      "construction_costs.land_cost",
      "construction_costs.land_cost_total",
      "construction_costs.contingency",
      "construction_costs.contingency_total",
      "deal_structure.total_project_cost",
    ],
  },
  {
    test: (name) => name.includes("irr"),
    area: "Returns",
    primary: "target_returns.target_irr",
    inputs: ["target_returns.target_irr", "target_returns.net_irr", "target_returns.target_cash_on_cash", "target_returns.distribution_yield"],
  },
  {
    test: (name) => name.includes("multiple"),
    area: "Returns",
    primary: "target_returns.target_equity_multiple",
    inputs: ["target_returns.target_equity_multiple", "target_returns.net_equity_multiple"],
  },
];

export function ReviewQueue({ deal }: { deal: DealDetail }) {
  const items = buildReviewItems(deal);

  if (items.length === 0) return <ReviewQueueEmptyState />;

  return (
    <Card className="border-border/80 bg-card p-5 shadow-sm md:p-6">
      <ReviewQueueHeader count={items.length} />
      <div className="mt-4 space-y-2.5">
        {items.map((item, index) => (
          <ReviewRow key={item.key} dealId={deal.id} item={item} index={index} />
        ))}
      </div>
    </Card>
  );
}

function ReviewRow({ dealId, item, index }: { dealId: number; item: ReviewItem; index: number }) {
  const [editing, setEditing] = React.useState(false);
  const [sourceOpen, setSourceOpen] = React.useState(false);
  const hasInputs = Boolean(item.inputs?.length);
  const primaryInput = item.inputs?.[0];
  const sourcePath = item.path ?? primaryInput?.path;
  const sourceValue = item.path ? item.value : primaryInput?.value;
  const sourceProvenance = item.path ? item.provenance : primaryInput?.provenance;
  const Icon = item.kind === "math" ? Calculator : item.kind === "source" ? FileText : AlertTriangle;

  return (
    <div className={cn("overflow-hidden rounded-xl border bg-background", item.severity === "red" ? "border-destructive/25" : "border-warning/25")}>
      <div className="grid gap-4 p-4 md:grid-cols-[1fr_auto] md:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md ring-1", item.severity === "red" ? "bg-destructive/10 text-destructive ring-destructive/25" : "bg-warning/10 text-warning ring-warning/25")}>
              <Icon className="h-3.5 w-3.5" />
            </span>
            <h4 className="text-sm font-extrabold tracking-tight text-foreground">{item.title}</h4>
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground ring-1 ring-border/70">{item.area}</span>
            <span className="text-[10px] font-semibold text-muted-foreground">#{index + 1}</span>
          </div>
          <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{item.detail}</p>
          {(item.value !== undefined || item.source) && (
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
              {item.value !== undefined ? <span>Current <span className="font-bold text-foreground">{formatReviewValue(item.value, item.path)}</span></span> : null}
              {item.source ? <span>Source <span className="font-medium text-foreground">{item.source}</span></span> : null}
            </div>
          )}
          {hasInputs && !editing ? <ReviewInputSummary inputs={item.inputs ?? []} /> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 md:max-w-[24rem] md:justify-end">
          {sourcePath ? (
            <Button size="sm" variant="outline" onClick={() => setSourceOpen(true)}>
              <Search className="h-3.5 w-3.5" />
              Inspect source
            </Button>
          ) : null}
          {hasInputs ? (
            <Button size="sm" variant={editing ? "secondary" : "outline"} onClick={() => setEditing((value) => !value)}>
              {editing ? "Hide values" : "Edit values"}
            </Button>
          ) : null}
          <ResolveButton dealId={dealId} item={item} action="unsure" label="Unsure" variant="secondary" />
          <ResolveButton dealId={dealId} item={item} action="confirmed" label={item.confirmLabel ?? "Confirm"} />
        </div>
      </div>
      {editing && hasInputs ? <ReviewInputEditor dealId={dealId} item={item} onDone={() => setEditing(false)} /> : null}
      {sourcePath ? (
        <SourceDetailsDrawer
          open={sourceOpen}
          onOpenChange={setSourceOpen}
          label={humanizePath(sourcePath)}
          value={formatReviewValue(sourceValue, sourcePath)}
          rawValue={sourceValue}
          path={sourcePath}
          provenance={sourceProvenance}
          issueTitle={item.title}
          issueDetail={item.detail}
          issueWhy={whyThisMatters(item)}
          dealId={dealId}
          showAdminAction
          inputs={(item.inputs ?? []).map((input) => ({
            label: input.label,
            value: formatReviewValue(input.value, input.path),
            path: input.path,
            provenance: input.provenance,
          }))}
        />
      ) : null}
    </div>
  );
}

function ResolveButton({
  dealId,
  item,
  action,
  label,
  variant = "default",
}: {
  dealId: number;
  item: ReviewItem;
  action: "confirmed" | "unsure";
  label: string;
  variant?: React.ComponentProps<typeof Button>["variant"];
}) {
  const [busy, setBusy] = React.useState(false);

  async function resolve() {
    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/reviews/resolve`, {
        key: item.key,
        action,
        note: action === "unsure" ? "Marked unsure from the admin review queue. Do not treat this item as verified." : "Confirmed from the admin review queue.",
      });
      toast.success(action === "unsure" ? "Marked unsure" : "Review item cleared", {
        description: action === "unsure" ? "The item is removed from the checklist and kept in the audit trail as uncertain." : "The item was confirmed and removed from Needs review.",
      });
      window.location.reload();
    } catch (error) {
      toast.error("Could not update review item", { description: errorDetail(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button size="sm" variant={variant} onClick={resolve} disabled={busy}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : action === "unsure" ? <HelpCircle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
      {label}
    </Button>
  );
}

function ReviewInputSummary({ inputs }: { inputs: ReviewInput[] }) {
  return (
    <div className="mt-2.5 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
      <div className="mb-1.5 text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">Key values</div>
      <div className="flex flex-wrap gap-1.5">
        {inputs.slice(0, 8).map((input) => (
          <span key={input.path} className="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
            {input.label}: <span className="font-bold text-foreground">{formatReviewValue(input.value, input.path)}</span>
          </span>
        ))}
        {inputs.length > 8 ? <span className="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">+{inputs.length - 8} more</span> : null}
      </div>
    </div>
  );
}

function ReviewInputEditor({ dealId, item, onDone }: { dealId: number; item: ReviewItem; onDone?: () => void }) {
  const inputs = (item.inputs ?? []).filter((input) => isEditableValue(input.value));
  const [drafts, setDrafts] = React.useState<Record<string, string>>(() => Object.fromEntries(inputs.map((input) => [input.path, scalarToInput(input.value)])));
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    setDrafts(Object.fromEntries(inputs.map((input) => [input.path, scalarToInput(input.value)])));
  }, [item.key]);

  async function saveAll() {
    const edits = inputs.map((input) => ({ path: input.path, value: parseDraftValue(drafts[input.path] ?? "", input.value), lock: true }));
    if (!edits.length) {
      toast.error("Nothing to save", { description: "This item does not have editable values." });
      return;
    }

    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/batch-edit`, {
        edits,
        review_key: item.key,
        review_action: "inputs_saved",
        review_note: `${edits.length} field${edits.length === 1 ? "" : "s"} reviewed from the Needs review queue.`,
      });
      toast.success("Inputs saved and item cleared", { description: `${edits.length} field${edits.length === 1 ? "" : "s"} updated.` });
      onDone?.();
      window.location.reload();
    } catch (error) {
      toast.error("Could not save inputs", { description: errorDetail(error) });
    } finally {
      setBusy(false);
    }
  }

  if (!inputs.length) return null;

  return (
    <div className="border-t border-border/70 bg-primary/5 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-extrabold text-foreground">Edit or confirm values</div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Update wrong values, or save unchanged values to approve and clear this row.</p>
        </div>
        <Button size="sm" onClick={saveAll} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          Save and clear
        </Button>
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        {inputs.map((input) => (
          <div key={input.path} className="rounded-lg border border-border/70 bg-background/80 p-2.5">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="text-[11px] font-bold text-muted-foreground">{input.label}</div>
              <a href={sourceHref(input.path)} className="text-[11px] font-semibold text-primary hover:underline">source</a>
            </div>
            <input
              value={drafts[input.path] ?? ""}
              onChange={(event) => setDrafts((prev) => ({ ...prev, [input.path]: event.target.value }))}
              placeholder="missing or 65.95M"
              className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring"
            />
            <div className="mt-1 text-[10px] text-muted-foreground">{input.path}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function buildReviewItems(deal: DealDetail): ReviewItem[] {
  const metrics = (deal.metrics ?? {}) as Metrics;
  const gate = (deal.scores?.data_quality ?? metrics._data_quality) as ReviewGate | undefined;
  const provenance = metrics._provenance ?? {};
  const flags = Array.isArray(metrics.validation_flags) ? metrics.validation_flags : [];
  const items = [
    ...mathItems(gate, metrics, provenance),
    ...flagItems(flags, metrics, provenance),
    ...criticalFieldItems(gate, metrics, provenance),
    ...sourceItems(metrics, provenance),
  ];
  return dedupeItems(items)
    .filter((item) => !isReviewResolved(metrics, item.key))
    .sort((a, b) => b.priority - a.priority);
}

function mathItems(gate: ReviewGate | undefined, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  const checks = blockingMathChecks(gate, metrics).filter((check) => !mathCheckLooksResolved(check, metrics));
  return checks.map((check, index) => {
    const config = mathConfig(check.check ?? "");
    const path = config?.primary;
    const inputs = (config?.inputs ?? []).map((inputPath) => reviewInput(inputPath, metrics, provenance)).filter(Boolean) as ReviewInput[];
    return {
      key: `math:${check.check ?? index}`,
      priority: 100 - index,
      kind: "math",
      area: config?.area ?? "Math",
      severity: "red",
      title: check.check || "Math check failed",
      detail: [check.difference, check.formula, check.message].filter(Boolean).join(" - ") || "A saved calculation does not reconcile.",
      path,
      value: path ? getPath(metrics, path) : undefined,
      source: path ? sourceLabel(provenance[path]) : undefined,
      provenance: path ? provenance[path] : undefined,
      inputs,
    };
  });
}

function flagItems(flags: ValidationFlag[], metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  return flags
    .filter((flag) => ["red", "yellow"].includes(String(flag.severity)))
    .map((flag, index) => {
      const path = bestPathFromMessage(flag.message);
      const area = areaForFlag(flag, path);
      const inputs = inputsForMessage(flag.message, path, area, metrics, provenance);
      return {
        key: `flag:${flag.category}:${path ?? flag.message}`,
        priority: flag.severity === "red" ? 82 - index : 45 - index,
        kind: "flag",
        area,
        severity: flag.severity === "red" ? "red" : "yellow",
        title: `${titleCase(flag.category || area)} needs review`,
        detail: flag.message,
        path,
        value: path ? getPath(metrics, path) : undefined,
        source: path ? sourceLabel(provenance[path]) : undefined,
        provenance: path ? provenance[path] : undefined,
        inputs,
        confirmLabel: "Accept note",
      } satisfies ReviewItem;
    });
}

function criticalFieldItems(gate: ReviewGate | undefined, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  const fields = Array.isArray(gate?.critical_fields) ? gate.critical_fields : [];
  return fields
    .filter((field) => !field.verified && field.severity !== "ok")
    .map((field, index) => {
      const path = field.actual_path || field.path;
      const input = reviewInput(path, metrics, provenance);
      return {
        key: `field:${path}`,
        priority: field.severity === "blocker" ? 78 - index : 48 - index,
        kind: "source",
        area: areaForPath(path),
        severity: field.severity === "blocker" ? "red" : "yellow",
        title: `${field.label || humanizePath(path)} needs review`,
        detail: field.reason || `${field.label || humanizePath(path)} needs a human check.`,
        path,
        value: getPath(metrics, path),
        source: sourceLabel(provenance[path]),
        provenance: provenance[path],
        inputs: input ? [input] : undefined,
      } satisfies ReviewItem;
    });
}

function sourceItems(metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewItem[] {
  return Object.entries(provenance).flatMap(([path, source], index) => {
    const status = String(source.status ?? "").toLowerCase();
    const conflicts = Array.isArray(source.conflict) ? source.conflict.length : 0;
    const lowConfidence = typeof source.confidence === "number" && source.confidence < REVIEW_THRESHOLD;
    if (!BAD_SOURCE_STATUSES.has(status) && conflicts <= 1 && !lowConfidence) return [];
    const input = reviewInput(path, metrics, provenance);
    return [{
      key: `source:${path}`,
      priority: BAD_SOURCE_STATUSES.has(status) || conflicts > 1 ? 70 - index : 34 - index,
      kind: "source",
      area: areaForPath(path),
      severity: BAD_SOURCE_STATUSES.has(status) || conflicts > 1 ? "red" : "yellow",
      title: `${humanizePath(path)} needs review`,
      detail: sourceDetail(source),
      path,
      value: getPath(metrics, path),
      source: sourceLabel(source),
      provenance: source,
      inputs: input ? [input] : undefined,
    } satisfies ReviewItem];
  });
}

function blockingMathChecks(gate: ReviewGate | undefined, metrics: Metrics): MathCheck[] {
  const fromGate = gate?.math_summary?.blocking;
  if (Array.isArray(fromGate)) return fromGate as MathCheck[];
  const fromMetrics = metrics._math_checks?.summary?.blocking;
  return Array.isArray(fromMetrics) ? (fromMetrics as MathCheck[]) : [];
}

function reviewInput(path: string, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewInput | null {
  const meta = FIELD_META[path] ?? { label: humanizePath(path), format: guessFormat(path) };
  return { path, label: meta.label, format: meta.format, value: getPath(metrics, path), provenance: provenance[path] };
}

function inputsForMessage(message: string, path: string | undefined, area: ReviewArea, metrics: Metrics, provenance: Record<string, FieldProvenance>): ReviewInput[] | undefined {
  const paths = new Set<string>();
  if (path) paths.add(path);
  for (const match of message.match(/[a-z_]+\.[a-z_]+/g) ?? []) {
    if (FIELD_META[match]) paths.add(match);
  }
  if (paths.size === 0) {
    for (const fallback of fallbackPaths(area)) paths.add(fallback);
  }
  const inputs = Array.from(paths).map((itemPath) => reviewInput(itemPath, metrics, provenance)).filter(Boolean) as ReviewInput[];
  return inputs.length ? inputs : undefined;
}

function fallbackPaths(area: ReviewArea): string[] {
  if (area === "Returns") return ["target_returns.target_irr", "target_returns.net_irr", "target_returns.target_equity_multiple", "target_returns.net_equity_multiple"];
  if (area === "Debt") return ["underwriting_checks.dscr", "deal_structure.ltv", "deal_structure.debt_amount", "deal_structure.interest_rate"];
  if (area === "Construction") return ["construction_costs.hard_costs", "construction_costs.soft_costs", "construction_costs.land_cost", "construction_costs.contingency", "deal_structure.total_project_cost"];
  if (area === "Sponsor") return ["sponsor_evaluation.alignment_score", "sponsor_evaluation.sponsor_skin_in_game"];
  if (area === "Market") return ["financial_projections.entry_cap_rate", "financial_projections.exit_cap_rate", "financial_projections.occupancy_assumption"];
  return ["deal_structure.total_project_cost", "deal_structure.total_equity_required", "deal_structure.debt_amount"];
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

function isReviewResolved(metrics: Metrics, key: string): boolean {
  const resolutions = metrics._review_resolutions;
  if (!resolutions || typeof resolutions !== "object") return false;
  const map = resolutions as Record<string, unknown>;
  return isResolvedEntry(map[key]) || isResolvedEntry(map[reviewResolutionKey(key)]);
}

function isResolvedEntry(value: unknown): boolean {
  return value === true || Boolean(value && typeof value === "object" && (value as Record<string, unknown>).resolved === true);
}

function mathCheckLooksResolved(check: MathCheck, metrics: Metrics): boolean {
  const difference = String(check.difference ?? check.message ?? "");
  const match = difference.toLowerCase().match(/([0-9]+(?:\.[0-9]+)?)%\s+off/);
  if (match && Number(match[1]) <= 0.05) return true;
  const name = normalize(check.check ?? "");
  if (name.includes("dscr") || name.includes("debt service")) {
    const reported = numberValue(getPath(metrics, "underwriting_checks.dscr"));
    const noi = numberValue(getPath(metrics, "financial_projections.stabilized_noi"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    const rate = numberValue(getPath(metrics, "deal_structure.interest_rate"));
    return reported != null && noi != null && debt != null && rate != null && rate > 0 && Math.abs(noi / (debt * (rate / 100)) - reported) <= 0.05;
  }
  if (name.includes("ltv")) return formulaWithin(metrics, "deal_structure.ltv", "deal_structure.debt_amount", "deal_structure.total_project_cost", 0.5, 100);
  if (name.includes("irr")) return valuesWithin(metrics, "target_returns.target_irr", "target_returns.net_irr", 0.25);
  if (name.includes("multiple")) return valuesWithin(metrics, "target_returns.target_equity_multiple", "target_returns.net_equity_multiple", 0.02);
  if (name.includes("total project cost") && name.includes("equity")) {
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    const equity = numberValue(getPath(metrics, "deal_structure.total_equity_required"));
    const debt = numberValue(getPath(metrics, "deal_structure.debt_amount"));
    return total != null && equity != null && debt != null && Math.abs(total - (equity + debt)) <= 1;
  }
  if (name.includes("hard") && name.includes("soft") && name.includes("land")) {
    const total = numberValue(getPath(metrics, "deal_structure.total_project_cost"));
    const hard = firstNumber(metrics, ["construction_costs.hard_costs", "construction_costs.hard_costs_total"]);
    const soft = firstNumber(metrics, ["construction_costs.soft_costs", "construction_costs.soft_costs_total"]);
    const land = firstNumber(metrics, ["construction_costs.land_cost", "construction_costs.land_cost_total"]);
    const contingency = firstNumber(metrics, ["construction_costs.contingency", "construction_costs.contingency_total"]) ?? 0;
    return total != null && hard != null && soft != null && land != null && Math.abs(total - (hard + soft + land + contingency)) <= 1;
  }
  return false;
}

function valuesWithin(metrics: Metrics, leftPath: string, rightPath: string, tolerance: number): boolean {
  const left = numberValue(getPath(metrics, leftPath));
  const right = numberValue(getPath(metrics, rightPath));
  return left != null && right != null && Math.abs(left - right) <= tolerance;
}

function formulaWithin(metrics: Metrics, reportedPath: string, numeratorPath: string, denominatorPath: string, tolerance: number, multiplier = 1): boolean {
  const reported = numberValue(getPath(metrics, reportedPath));
  const numerator = numberValue(getPath(metrics, numeratorPath));
  const denominator = numberValue(getPath(metrics, denominatorPath));
  return reported != null && numerator != null && denominator != null && denominator > 0 && Math.abs((numerator / denominator) * multiplier - reported) <= tolerance;
}

function mathConfig(name: string) {
  const normalized = normalize(name);
  return MATH_CONFIGS.find((config) => config.test(normalized));
}

function bestPathFromMessage(message: string): string | undefined {
  const matches = message.match(/[a-z_]+\.[a-z_]+/g) ?? [];
  return matches.find((path) => path.includes("target_")) ?? matches.find((path) => path.includes("net_")) ?? matches.find((path) => FIELD_META[path]) ?? matches[0];
}

function areaForFlag(flag: ValidationFlag, path?: string): ReviewArea {
  const category = String(flag.category ?? "").toLowerCase();
  if (category.includes("return") || path?.startsWith("target_returns")) return "Returns";
  if (category.includes("debt") || category.includes("leverage") || path?.includes("debt") || path?.includes("ltv")) return "Debt";
  if (category.includes("sponsor") || category.includes("alignment")) return "Sponsor";
  if (category.includes("market")) return "Market";
  if (category.includes("source")) return "Source";
  if (category.includes("construction") || path?.startsWith("construction_costs")) return "Construction";
  return path ? areaForPath(path) : "Capital Stack";
}

function areaForPath(path: string): ReviewArea {
  if (path.startsWith("target_returns")) return "Returns";
  if (path.includes("debt") || path.includes("ltv") || path.includes("dscr")) return "Debt";
  if (path.startsWith("construction_costs")) return "Construction";
  if (path.startsWith("sponsor_evaluation")) return "Sponsor";
  if (path.startsWith("market_location") || path.startsWith("financial_projections")) return "Market";
  return "Capital Stack";
}

function sourceDetail(source: FieldProvenance): string {
  const conflicts = Array.isArray(source.conflict) ? source.conflict.length : 0;
  if (conflicts > 1) return "Documents disagree. Pick the correct value, confirm the current value, or mark it unsure.";
  if (source.status === "missing") return "This field was not found in the documents. Add it, confirm it is not available, or mark it unsure.";
  if (source.status === "wrong") return "Verification challenged this value. Edit it or confirm the current value.";
  if (source.status === "unverifiable") return "The app could not tie this value back to a clear source document.";
  if (typeof source.confidence === "number") return `Only ${source.confidence}% confidence. Confirm it, edit it, or mark it unsure.`;
  return "This value needs human review before the score is trusted.";
}

function whyThisMatters(item: ReviewItem): string {
  if (item.kind === "math") return "A failed calculation can make the score and comparison unreliable.";
  if (item.kind === "source") return "The score should only rely on values tied to a source, confirmed by admin, or marked unsure.";
  if (item.area === "Returns") return "Return assumptions drive the headline score and investor comparison.";
  if (item.area === "Debt") return "Debt assumptions affect leverage, DSCR, and downside risk.";
  if (item.area === "Sponsor") return "Sponsor alignment affects execution trust and risk scoring.";
  return "This item should be cleared before the score is treated as final.";
}

function sourceLabel(source?: FieldProvenance): string | undefined {
  if (!source?.source_doc_name) return undefined;
  return `${source.source_doc_name}${source.source_page ? ` p.${source.source_page}` : ""}`;
}

function getPath(data: unknown, path?: string): unknown {
  if (!path) return undefined;
  let current = data;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value.replace(/[$,%x]/gi, "").replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function firstNumber(metrics: Metrics, paths: string[]): number | null {
  for (const path of paths) {
    const value = numberValue(getPath(metrics, path));
    if (value != null) return value;
  }
  return null;
}

function isEditableValue(value: unknown): boolean {
  return value == null || ["string", "number", "boolean"].includes(typeof value);
}

function scalarToInput(value: unknown): string {
  if (value == null) return "";
  return ["string", "number", "boolean"].includes(typeof value) ? String(value) : "";
}

function parseDraftValue(value: string, original: unknown): string | number | boolean | null {
  const raw = value.trim();
  if (!raw) return null;
  const compact = raw.replace(/[$,%x]/gi, "").replace(/,/g, "");
  if (typeof original === "boolean") return ["true", "1", "yes"].includes(compact.toLowerCase());
  const numeric = compact.match(/^(-?\d+(?:\.\d+)?)(k|mm|m|b)?$/i);
  if (!numeric) return raw;
  const multipliers: Record<string, number> = { k: 1000, m: 1000000, mm: 1000000, b: 1000000000 };
  return Number(numeric[1]) * (multipliers[(numeric[2] ?? "").toLowerCase()] ?? 1);
}

function formatReviewValue(value: unknown, path?: string): string {
  if (value == null || value === "") return "missing";
  const numeric = numberValue(value);
  if (numeric == null) return String(value);
  const format = (path && FIELD_META[path]?.format) ?? guessFormat(path ?? "");
  if (format === "pct") return fmtPct(numeric, 1);
  if (format === "money") return fmtMoney(numeric);
  if (format === "multiple") return fmtMultiple(numeric);
  if (format === "integer") return Math.round(numeric).toLocaleString();
  return String(value);
}

function guessFormat(path: string): FieldFormat {
  if (path.includes("irr") || path.includes("rate") || path.includes("ltv") || path.includes("pct") || path.includes("yield") || path.includes("occupancy") || path.includes("return")) return "pct";
  if (path.includes("multiple") || path.includes("dscr")) return "multiple";
  if (path.includes("count") || path.includes("year") || path.includes("term") || path.includes("score")) return "integer";
  if (path.includes("cost") || path.includes("amount") || path.includes("noi") || path.includes("equity") || path.includes("debt") || path.includes("rent") || path.includes("revenue") || path.includes("investment")) return "money";
  return "text";
}

function humanizePath(path: string): string {
  const field = path.split(".").at(-1) ?? path;
  return FIELD_META[path]?.label ?? titleCase(field.replace(/_/g, " "));
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function sourceHref(path?: string): string {
  return path ? `#source-citation-${path.replace(/[^a-zA-Z0-9_-]+/g, "-")}` : "#technical-details";
}

function reviewResolutionKey(key: string): string {
  return encodeURIComponent(key).replace(/\./g, "%2E");
}

function errorDetail(error: unknown): string {
  if (!error) return "The server did not return a reason.";
  const detail = (error as { detail?: unknown; message?: unknown })?.detail ?? (error as { message?: unknown })?.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return "The server returned an unreadable error.";
    }
  }
  return "The server did not return a reason.";
}
