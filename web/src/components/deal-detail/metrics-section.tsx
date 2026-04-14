"use client";

import { Card } from "@/components/ui/card";
import { cn, fmtMoney, fmtPct } from "@/lib/utils";

/**
 * Render a metrics section as a definition-list of key/value pairs with
 * smart formatting. Currency/percentage/multiple/integer fields are
 * detected heuristically by name; strings just render as-is.
 *
 * This keeps the UI resilient to the backend adding new fields — they'll
 * just appear. Unknown fields get basic formatting.
 */
export function MetricsSection({
  title,
  description,
  data,
  keysOrder,
}: {
  title: string;
  description?: string;
  data: Record<string, unknown> | undefined;
  keysOrder?: readonly string[];
}) {
  if (!data || typeof data !== "object" || Object.keys(data).length === 0) {
    return (
      <Card elevated className="p-6">
        <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
        {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
        <div className="text-xs text-muted-foreground mt-4">Not yet extracted.</div>
      </Card>
    );
  }

  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== "" && v !== undefined);
  if (keysOrder) {
    entries.sort(([a], [b]) => {
      const ai = keysOrder.indexOf(a);
      const bi = keysOrder.indexOf(b);
      if (ai === -1 && bi === -1) return a.localeCompare(b);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }

  return (
    <Card elevated className="p-6">
      <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
      {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
      <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
        {entries.map(([k, v]) => (
          <MetricRow key={k} name={k} value={v} />
        ))}
      </dl>
    </Card>
  );
}

function MetricRow({ name, value }: { name: string; value: unknown }) {
  const label = humanize(name);
  const formatted = formatValue(name, value);
  const isLong = typeof value === "string" && value.length > 80;

  if (isLong) {
    return (
      <div className="sm:col-span-2 py-1.5">
        <dt className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground mb-1">{label}</dt>
        <dd className="text-sm leading-relaxed text-foreground/90">{formatted}</dd>
      </div>
    );
  }

  return (
    <div className="flex justify-between gap-4 border-b border-border/50 last:border-0 py-1.5">
      <dt className="text-xs text-muted-foreground truncate">{label}</dt>
      <dd className={cn("text-sm text-right font-medium tabular-nums shrink-0")}>{formatted}</dd>
    </div>
  );
}

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase())
    .replace(/\bIrr\b/, "IRR")
    .replace(/\bLtv\b/, "LTV")
    .replace(/\bNoi\b/, "NOI")
    .replace(/\bGp\b/, "GP")
    .replace(/\bLp\b/, "LP")
    .replace(/\bDscr\b/, "DSCR")
    .replace(/\bPct\b/, "%")
    .replace(/\bSqft\b/, "Sqft");
}

function formatValue(name: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ") || "—";
  if (typeof value === "object") return JSON.stringify(value);

  if (typeof value === "number") {
    const n = name.toLowerCase();
    if (/(pct|percent|rate|yield|growth|margin|occupancy|ltv|return|coc|irr|dscr)/.test(n)) {
      return fmtPct(value, 1);
    }
    if (/(multiple)/.test(n)) return `${value.toFixed(2)}x`;
    if (/(amount|cost|budget|investment|loan|equity|profit|fee|revenue|expense|noi|rent|price|value)/.test(n)) {
      // fee_* fields on deal_structure are percentages, not dollars
      if (/^fees_/.test(n) && Math.abs(value) <= 10) return fmtPct(value, 2);
      return fmtMoney(value);
    }
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}
