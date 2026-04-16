"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { IntegrityBadge } from "@/components/deal-detail/integrity-badge";
import { ConflictPicker } from "@/components/deal-detail/conflict-picker";
import { cn, fmtMoney, fmtPct } from "@/lib/utils";
import type { FieldProvenance } from "@/lib/types";

/**
 * Render a metrics section as a definition-list of key/value pairs with
 * smart formatting. Currency/percentage/multiple/integer fields are
 * detected heuristically by name; strings just render as-is.
 *
 * The optional `provenance` prop maps a dotted `section.field` key to a
 * FieldProvenance record — when provided, each row shows an integrity badge
 * and any cross-document conflict gets an inline resolve button.
 */
export function MetricsSection({
  title,
  description,
  sectionKey,
  data,
  keysOrder,
  provenance,
  dealId,
}: {
  title: string;
  description?: string;
  sectionKey?: string;
  data: Record<string, unknown> | undefined;
  keysOrder?: readonly string[];
  provenance?: Record<string, FieldProvenance>;
  dealId?: number;
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

  const entries = Object.entries(data).filter(([, v]) => {
    if (v === null || v === "" || v === undefined) return false;
    // Empty arrays / empty objects add visual noise without carrying info.
    if (Array.isArray(v) && v.length === 0) return false;
    if (typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0) {
      return false;
    }
    return true;
  });
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
        {entries.map(([k, v]) => {
          const path = sectionKey ? `${sectionKey}.${k}` : undefined;
          const prov = path ? provenance?.[path] : undefined;
          return <MetricRow key={k} name={k} value={v} provenance={prov} path={path} dealId={dealId} />;
        })}
      </dl>
    </Card>
  );
}

function MetricRow({
  name,
  value,
  provenance,
  path,
  dealId,
}: {
  name: string;
  value: unknown;
  provenance?: FieldProvenance;
  path?: string;
  dealId?: number;
}) {
  const label = humanize(name);
  const formatted = formatValue(name, value);
  // Long content — either original strings >80 chars OR object descriptions
  // we unwrapped above — needs to span both grid columns so it wraps
  // cleanly instead of pushing past the card's right edge.
  const isLong =
    (typeof value === "string" && value.length > 80) ||
    (typeof value === "object" && value !== null && !Array.isArray(value) && formatted.length > 80);
  const hasConflict =
    Array.isArray(provenance?.conflict) && (provenance!.conflict as unknown[]).length > 1;

  if (isLong) {
    return (
      <div className="sm:col-span-2 py-1.5">
        <dt className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground mb-1 flex items-center gap-1.5">
          {label}
          <IntegrityBadge provenance={provenance} compact />
        </dt>
        <dd className="text-sm leading-relaxed text-foreground/90">{formatted}</dd>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex justify-between items-center gap-4 border-b border-border/50 last:border-0 py-1.5",
        hasConflict && "bg-destructive/5 -mx-2 px-2 rounded-md",
      )}
    >
      <dt className="text-xs text-muted-foreground truncate flex items-center gap-1.5">
        <span className="truncate">{label}</span>
        <IntegrityBadge provenance={provenance} compact />
      </dt>
      <dd className="flex items-center gap-2 shrink-0">
        <span className="text-sm text-right font-medium tabular-nums">{formatted}</span>
        {hasConflict && path && dealId && provenance?.conflict && (
          <ConflictPicker dealId={dealId} path={path} conflict={provenance.conflict} currentValue={value} />
        )}
      </dd>
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
  if (typeof value === "object") {
    // Some extracted fields (e.g. hold_scenario, sale_scenario) come back
    // as nested objects. Raw JSON.stringify makes the card overflow and
    // duplicates data that's already in sibling scalar fields. Prefer
    // `description` when present; otherwise fall back to a short summary
    // of the sub-keys so the field isn't silently blank.
    const obj = value as Record<string, unknown>;
    const desc = obj.description;
    if (typeof desc === "string" && desc.trim()) return desc;
    const keys = Object.keys(obj).filter((k) => obj[k] != null);
    if (keys.length === 0) return "—";
    return keys.map(humanize).join(", ");
  }

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
