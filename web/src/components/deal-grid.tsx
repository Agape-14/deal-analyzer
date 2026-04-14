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
} from "lucide-react";
import type { DealStatus, DealSummary } from "@/lib/types";
import { DealCard } from "@/components/deal-card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type SortKey = "score" | "irr" | "multiple" | "recent" | "name";

const SORTS: Array<{ key: SortKey; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "score", label: "Score", icon: Sparkles },
  { key: "irr", label: "Target IRR", icon: TrendingUp },
  { key: "multiple", label: "Multiple", icon: ArrowDownUp },
  { key: "recent", label: "Most recent", icon: Clock },
  { key: "name", label: "Name (A–Z)", icon: CircleDot },
];

const STATUSES: Array<{ key: DealStatus | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "reviewing", label: "Reviewing" },
  { key: "interested", label: "Interested" },
  { key: "committed", label: "Committed" },
  { key: "closed", label: "Closed" },
  { key: "passed", label: "Passed" },
];

/**
 * Client-side filter/sort UI over a server-fetched deal list.
 *
 * We do the filtering locally because dashboards feel broken when each
 * pill-click round-trips the server. If the list grows past a few hundred
 * we'll switch to URL-driven params + a paginated API.
 */
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

  return (
    <div>
      {/* Toolbar */}
      <div className="mb-6 flex flex-col md:flex-row md:items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by project, sponsor, city…"
            className="pl-9"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Status pills */}
          <div className="flex items-center gap-1 p-1 rounded-lg bg-secondary/40 border border-border/70 relative">
            {STATUSES.map((s) => {
              const active = status === s.key;
              return (
                <button
                  key={s.key}
                  onClick={() => setStatus(s.key)}
                  className={cn(
                    "relative z-10 px-2.5 h-7 text-xs font-medium rounded-md transition-colors",
                    active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="status-pill"
                      className="absolute inset-0 rounded-md bg-card ring-1 ring-border/80 shadow-sm"
                      transition={{ type: "spring", stiffness: 420, damping: 32 }}
                    />
                  )}
                  <span className="relative">{s.label}</span>
                </button>
              );
            })}
          </div>

          {/* Sort */}
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
                  className="absolute right-0 top-full mt-1.5 w-48 rounded-lg border border-border/80 bg-card shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-1 z-30"
                >
                  {SORTS.map((s) => (
                    <button
                      key={s.key}
                      onMouseDown={(e) => {
                        // mouseDown so the click fires before the blur handler above
                        e.preventDefault();
                        setSort(s.key);
                        setSortOpen(false);
                      }}
                      className={cn(
                        "w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs transition-colors",
                        s.key === sort
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:text-foreground hover:bg-muted/60",
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

      {/* Result count */}
      <div className="mb-3 text-xs text-muted-foreground">
        {filtered.length} of {deals.length} deal{deals.length === 1 ? "" : "s"}
        {query && (
          <>
            {" "}
            matching <span className="text-foreground">&ldquo;{query}&rdquo;</span>
          </>
        )}
      </div>

      {/* Grid — each card animates in/out via layout + AnimatePresence */}
      <motion.div layout className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
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
  );
}
