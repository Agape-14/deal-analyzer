"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Building2, Mail, Phone, ArrowUpRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { Developer, DealSummary } from "@/lib/types";
import { cn, fmtPct } from "@/lib/utils";

/**
 * Sponsor tile with aggregated stats computed client-side from the deals
 * list (since the backend doesn't return per-developer analytics). Keeps
 * card height stable whether a sponsor has 0 deals or 30.
 */
export function DeveloperCard({
  developer,
  deals,
}: {
  developer: Developer;
  deals: DealSummary[];
}) {
  const ownDeals = deals.filter((d) => d.developer_id === developer.id);
  const scored = ownDeals.filter((d) => d.overall_score != null);
  const avgScore = scored.length
    ? scored.reduce((a, d) => a + (d.overall_score ?? 0), 0) / scored.length
    : null;
  const irrs = ownDeals.map((d) => d.target_irr).filter((x): x is number => typeof x === "number");
  const avgIrr = irrs.length ? irrs.reduce((a, b) => a + b, 0) / irrs.length : null;

  const statusCounts = ownDeals.reduce<Record<string, number>>((m, d) => {
    m[d.status] = (m[d.status] ?? 0) + 1;
    return m;
  }, {});

  return (
    <Link href={`/developers/${developer.id}`} className="block group outline-none">
      <motion.div layout>
        <Card
          elevated
          className="p-5 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:shadow-[0_20px_60px_-30px_hsl(var(--primary)/.4)] group-focus-visible:ring-2 group-focus-visible:ring-ring"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2.5">
                <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-primary/15 to-chart-3/15 ring-1 ring-border/60 grid place-items-center shrink-0">
                  <Building2 className="h-4 w-4 text-primary" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold tracking-tight truncate">{developer.name}</h3>
                  {developer.contact_name && (
                    <div className="text-xs text-muted-foreground truncate">{developer.contact_name}</div>
                  )}
                </div>
              </div>

              {(developer.contact_email || developer.phone) && (
                <div className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
                  {developer.contact_email && (
                    <span className="inline-flex items-center gap-1 truncate">
                      <Mail className="h-3 w-3 shrink-0" />
                      <span className="truncate">{developer.contact_email}</span>
                    </span>
                  )}
                  {developer.phone && (
                    <span className="inline-flex items-center gap-1 truncate">
                      <Phone className="h-3 w-3 shrink-0" />
                      <span className="truncate">{developer.phone}</span>
                    </span>
                  )}
                </div>
              )}
            </div>
            <ArrowUpRight className="h-4 w-4 text-muted-foreground group-hover:text-foreground group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
          </div>

          {/* Stats row */}
          <div className="mt-5 grid grid-cols-3 gap-3">
            <Stat label="Deals" value={String(developer.deal_count ?? ownDeals.length)} />
            <Stat label="Avg score" value={avgScore != null ? avgScore.toFixed(1) : "—"} />
            <Stat label="Avg target IRR" value={fmtPct(avgIrr)} />
          </div>

          {/* Status breakdown */}
          {ownDeals.length > 0 && (
            <div className="mt-4 pt-4 border-t border-border/50 flex items-center gap-2 flex-wrap">
              {(["interested", "reviewing", "committed", "closed", "passed"] as const).map((s) =>
                statusCounts[s] ? (
                  <span
                    key={s}
                    className={cn("text-[10px] uppercase tracking-wider rounded-full px-2 py-0.5", STATUS[s])}
                  >
                    {statusCounts[s]} {s}
                  </span>
                ) : null,
              )}
            </div>
          )}
        </Card>
      </motion.div>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums mt-1">{value}</div>
    </div>
  );
}

const STATUS: Record<string, string> = {
  reviewing: "bg-muted/60 text-muted-foreground",
  interested: "bg-primary/15 text-primary ring-1 ring-primary/30",
  passed: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
  committed: "bg-success/15 text-success ring-1 ring-success/30",
  closed: "bg-chart-3/15 text-[hsl(var(--chart-3))] ring-1 ring-[hsl(var(--chart-3))/.3]",
};
