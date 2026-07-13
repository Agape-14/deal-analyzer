"use client";

import * as React from "react";
import Link from "next/link";
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
  GitCompareArrows,
} from "lucide-react";
import type { DealStatus, DealSummary } from "@/lib/types";
import { DealCard } from "@/components/deal-card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/lib/auth-client";
import { cn, fmtMoney } from "@/lib/utils";

type SortKey = "score" | "irr" | "multiple" | "recent" | "name";

const SORTS: Array<{ key: SortKey; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "score", label: "Score", icon: Sparkles },
  { key: "irr", label: "Return", icon: TrendingUp },
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
  const { isAnalyst, loading } = useCurrentUser();
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
          return ((b.target_irr ?? b.target_cash_on_cash) ?? -1) - ((a.target_irr ?? a.target_cash_on_cash) ?? -1);
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
  const visibleExposure = filtered.reduce((sum, deal) => sum + (deal.minimum_investment ?? 0), 0);
  const showTeamCompare = !loading && !isAnalyst && deals.length > 1;

  return (
    <div className="relative z-10 clear-both">
      {showTeamCompare ? <TeamCompareBar deals={deals} /> : null}

      <div className="relative z-20 mb-6 flex flex-col gap-3 rounded-xl bg-background/90 xl:flex-row xl:items-center xl:justify-between">
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

      <motion.div layout className="relative z-0 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <AnimatePresence mode="popLayout">
          {filtered.map((deal) => (
            <motion.div
              key={deal.id}
              layout
              initial={{ opacity: 0, scale: 0.97, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            >
              <DealCard deal={deal} />
            </motion.div>
          ))}
        </AnimatePresence>
      </motion.div>

      {filtered.length === 0 && (
        <div className="rounded-xl border border-dashed border-border py-16 text-center text-sm text-muted-foreground">
          No deals match your filters.
        </div>
      )}
    </div>
  );
}

function TeamCompareBar({ deals }: { deals: DealSummary[] }) {
  const scored = deals.filter((deal) => typeof deal.overall_score === "number").length;
  const topDeal = [...deals].sort((a, b) => (b.overall_score ?? -1) - (a.overall_score ?? -1))[0];

  return (
    <div className="mb-6 overflow-hidden rounded-xl border border-border/80 bg-card/80 p-4 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-primary">Team comparison</div>
          <h2 className="mt-1 text-lg font-extrabold tracking-tight text-foreground">Compare the active deal set</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            {scored}/{deals.length} deals have scores. {topDeal ? `${topDeal.project_name} is currently the highest-ranked visible option.` : "Open the comparison table to review side by side."}
          </p>
        </div>
        <Button asChild>
          <Link href="/compare">
            <GitCompareArrows className="h-4 w-4" />
            Open compare view
          </Link>
        </Button>
      </div>
    </div>
  );
}
