"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Search,
  SlidersHorizontal,
  ArrowDownUp,
  CircleDot,
  TrendingUp,
  Sparkles,
  Clock,
  Check,
  Target,
  ClipboardCheck,
  Upload,
  GitCompareArrows,
} from "lucide-react";
import type { DealStatus, DealSummary } from "@/lib/types";
import { DealCard } from "@/components/deal-card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn, fmtMoney, fmtMultiple, fmtPct } from "@/lib/utils";

type SortKey = "score" | "irr" | "multiple" | "recent" | "name";

const SORTS: Array<{ key: SortKey; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "score", label: "Score", icon: Sparkles },
  { key: "irr", label: "Target IRR", icon: TrendingUp },
  { key: "multiple", label: "Multiple", icon: ArrowDownUp },
  { key: "recent", label: "Most recent", icon: Clock },
  { key: "name", label: "Name (A-Z)", icon: CircleDot },
];

const STATUSES: Array<{ key: DealStatus | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "reviewing", label: "Reviewing" },
  { key: "interested", label: "Interested" },
  { key: "committed", label: "Committed" },
  { key: "closed", label: "Closed" },
  { key: "passed", label: "Passed" },
];

export function DealGrid({ deals }: { deals: DealSummary[] }) {
  const [query, setQuery] = React.useState("");
  const [status, setStatus] = React.useState<DealStatus | "all">("all");
  const [sort, setSort] = React.useState<SortKey>("score");
  const [sortOpen, setSortOpen] = React.useState(false);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = deals;
    if (status !== "all") rows = rows.filter((d) => d.status === status);
    if (q) {
      rows = rows.filter(
        (d) =>
          d.project_name.toLowerCase().includes(q) ||
          d.developer_name.toLowerCase().includes(q) ||
          d.city.toLowerCase().includes(q) ||
          d.state.toLowerCase().includes(q),
      );
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      switch (sort) {
        case "score":
          return (b.overall_score ?? -1) - (a.overall_score ?? -1);
        case "irr":
          return (b.target_irr ?? -1) - (a.target_irr ?? -1);
        case "multiple":
          return (b.target_equity_multiple ?? -1) - (a.target_equity_multiple ?? -1);
        case "recent":
          return b.created_at.localeCompare(a.created_at);
        case "name":
          return a.project_name.localeCompare(b.project_name);
      }
    });
    return sorted;
  }, [deals, query, status, sort]);

  const activeSort = SORTS.find((s) => s.key === sort)!;
  const focusDeal = filtered[0] ?? null;
  const visibleExposure = filtered.reduce((sum, deal) => sum + (deal.minimum_investment ?? 0), 0);

  return (
    <div className="relative z-10 clear-both">
      <div className="relative z-20 mb-8 flex flex-col gap-3 rounded-xl bg-background/90 xl:flex-row xl:items-center xl:justify-between">
        <div className="relative w-full xl:max-w-[440px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by project, sponsor, city..."
            className="pl-9"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex items-center gap-1 rounded-lg border border-border/70 bg-secondary/40 p-1">
            {STATUSES.map((s) => {
              const active = status === s.key;
              return (
                <button
                  key={s.key}
                  onClick={() => setStatus(s.key)}
                  className={cn(
                    "relative z-10 h-7 rounded-md px-2.5 text-xs font-medium transition-colors",
                    active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="status-pill"
                      className="absolute inset-0 rounded-md bg-card shadow-sm ring-1 ring-border/80"
                      transition={{ type: "spring", stiffness: 420, damping: 32 }}
                    />
                  )}
                  <span className="relative">{s.label}</span>
                </button>
              );
            })}
          </div>

          <div className="relative">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setSortOpen((o) => !o)}
              onBlur={() => setTimeout(() => setSortOpen(false), 120)}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Sort:</span>
              <span className="font-medium">{activeSort.label}</span>
            </Button>
            <AnimatePresence>
              {sortOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.97 }}
                  transition={{ duration: 0.12, ease: [0.22, 1, 0.36, 1] }}
                  className="absolute right-0 top-full z-30 mt-1.5 w-48 rounded-lg border border-border/80 bg-card p-1 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)]"
                >
                  {SORTS.map((s) => (
                    <button
                      key={s.key}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setSort(s.key);
                        setSortOpen(false);
                      }}
                      className={cn(
                        "flex h-8 w-full items-center gap-2 rounded-md px-2.5 text-xs transition-colors",
                        s.key === sort
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                      )}
                    >
                      <s.icon className="h-3.5 w-3.5" />
                      <span className="flex-1 text-left font-medium">{s.label}</span>
                      {s.key === sort && <Check className="h-3.5 w-3.5" />}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      <div className="relative z-0 grid gap-6 xl:grid-cols-[minmax(360px,0.95fr)_minmax(300px,0.72fr)_minmax(300px,0.72fr)] xl:items-start 2xl:grid-cols-[minmax(420px,0.95fr)_minmax(340px,0.72fr)_minmax(340px,0.72fr)]">
        <div className="min-w-0">
          <div className="mb-4 flex min-h-5 items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              {filtered.length} of {deals.length} deal{deals.length === 1 ? "" : "s"}
              {query && (
                <>
                  {" "}
                  matching <span className="text-foreground">&quot;{query}&quot;</span>
                </>
              )}
            </span>
            <span className="hidden sm:inline tabular-nums">
              Visible exposure: <span className="font-medium text-foreground">{fmtMoney(visibleExposure)}</span>
            </span>
          </div>

          <motion.div layout className="relative z-0 grid grid-cols-1 gap-4 2xl:grid-cols-2">
            <AnimatePresence mode="popLayout">
              {filtered.map((deal) => (
                <motion.div
                  key={deal.id}
                  layout
                  initial={{ opacity: 0, scale: 0.95, y: 10 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                >
                  <DealCard deal={deal} />
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>

          {filtered.length === 0 && (
            <div className="py-16 text-center text-sm text-muted-foreground">
              No deals match your filters.
            </div>
          )}
        </div>

        <FocusPanel deal={focusDeal} visibleExposure={visibleExposure} />
        <NextActionsPanel deal={focusDeal} dealCount={filtered.length} />
      </div>
    </div>
  );
}

function FocusPanel({
  deal,
  visibleExposure,
}: {
  deal: DealSummary | null;
  visibleExposure: number;
}) {
  return (
    <aside className="overflow-hidden rounded-xl border border-border/80 bg-card/70 p-5 shadow-[0_0_0_1px_hsl(var(--border))_inset,0_20px_40px_-24px_hsl(0_0%_0%/0.7)] xl:sticky xl:top-[92px]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Focus</div>
          <h2 className="mt-1 text-sm font-semibold tracking-tight">
            {deal ? "Top visible deal" : "No visible deals"}
          </h2>
        </div>
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/20">
          <Target className="h-4 w-4" />
        </div>
      </div>

      {deal ? (
        <>
          <div className="mt-5 rounded-lg border border-border/70 bg-background/45 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-base font-semibold tracking-tight">{deal.project_name}</div>
                <div className="mt-1 truncate text-xs text-muted-foreground">{deal.developer_name}</div>
              </div>
              <div className="rounded-full bg-warning/15 px-2 py-1 text-xs font-semibold tabular-nums text-warning ring-1 ring-warning/30">
                {deal.overall_score == null ? "-" : deal.overall_score.toFixed(1)}
              </div>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-3">
              <MiniMetric label="IRR" value={fmtPct(deal.target_irr)} />
              <MiniMetric label="Multiple" value={fmtMultiple(deal.target_equity_multiple)} />
              <MiniMetric label="Min" value={fmtMoney(deal.minimum_investment)} />
            </div>
          </div>

          <div className="mt-4 space-y-3 text-xs">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Visible exposure</span>
              <span className="font-medium tabular-nums text-foreground">{fmtMoney(visibleExposure)}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Status</span>
              <span className="font-medium capitalize text-foreground">{deal.status}</span>
            </div>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          Adjust the filters to bring deals back into view.
        </div>
      )}
    </aside>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold tabular-nums tracking-tight">{value}</div>
    </div>
  );
}

function NextActionsPanel({
  deal,
  dealCount,
}: {
  deal: DealSummary | null;
  dealCount: number;
}) {
  const actions = deal
    ? [
        {
          icon: Upload,
          label: "Upload latest memo",
          detail: "Keep scoring current before comparing.",
        },
        {
          icon: ClipboardCheck,
          label: "Review extraction",
          detail: "Confirm IRR, multiple, and min investment.",
        },
        {
          icon: GitCompareArrows,
          label: "Compare alternatives",
          detail: dealCount > 1 ? "Use score and risk deltas." : "Add another deal to unlock a real comparison.",
        },
      ]
    : [
        {
          icon: Upload,
          label: "Add a deal",
          detail: "Upload an offering memo to populate the pipeline.",
        },
      ];

  return (
    <aside className="overflow-hidden rounded-xl border border-border/80 bg-card/70 p-5 shadow-[0_0_0_1px_hsl(var(--border))_inset,0_20px_40px_-24px_hsl(0_0%_0%/0.7)] xl:sticky xl:top-[92px]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Workflow</div>
          <h2 className="mt-1 text-sm font-semibold tracking-tight">Next actions</h2>
        </div>
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-success/10 text-success ring-1 ring-success/30">
          <ClipboardCheck className="h-4 w-4" />
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {actions.map((action) => (
          <div key={action.label} className="rounded-lg border border-border/70 bg-background/40 p-3">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
                <action.icon className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium tracking-tight">{action.label}</div>
                <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{action.detail}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
