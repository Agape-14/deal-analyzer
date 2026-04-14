"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, SlidersHorizontal, Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PositionCard } from "@/components/portfolio/position-card";
import { cn } from "@/lib/utils";
import type { Investment, InvestmentPerformance } from "@/lib/types";

type SortKey = "recent" | "invested" | "multiple" | "irr" | "name";
type StatusFilter = "all" | "active" | "exited" | "defaulted" | "pending";

const SORTS: Array<{ key: SortKey; label: string }> = [
  { key: "recent", label: "Most recent" },
  { key: "invested", label: "Capital (high → low)" },
  { key: "multiple", label: "Multiple (high → low)" },
  { key: "irr", label: "IRR (high → low)" },
  { key: "name", label: "Name (A–Z)" },
];

const STATUSES: Array<{ key: StatusFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "exited", label: "Exited" },
  { key: "defaulted", label: "Defaulted" },
  { key: "pending", label: "Pending" },
];

export function PositionGrid({
  investments,
  performance,
  onAddDistribution,
  onMarkExit,
}: {
  investments: Investment[];
  performance: Record<number, InvestmentPerformance>;
  onAddDistribution: (inv: Investment) => void;
  onMarkExit: (inv: Investment) => void;
}) {
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState<StatusFilter>("all");
  const [sort, setSort] = React.useState<SortKey>("recent");
  const [sortOpen, setSortOpen] = React.useState(false);

  const filtered = React.useMemo(() => {
    const needle = q.trim().toLowerCase();
    let rows = investments;
    if (status !== "all") rows = rows.filter((i) => i.status === status);
    if (needle) {
      rows = rows.filter(
        (i) =>
          i.project_name.toLowerCase().includes(needle) ||
          i.sponsor_name.toLowerCase().includes(needle),
      );
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      switch (sort) {
        case "invested":
          return (b.amount_invested ?? 0) - (a.amount_invested ?? 0);
        case "multiple":
          return (performance[b.id]?.multiple ?? b.actual_multiple ?? 0) - (performance[a.id]?.multiple ?? a.actual_multiple ?? 0);
        case "irr":
          return (performance[b.id]?.irr ?? -Infinity) - (performance[a.id]?.irr ?? -Infinity);
        case "name":
          return a.project_name.localeCompare(b.project_name);
        case "recent":
        default:
          return (b.investment_date ?? "").localeCompare(a.investment_date ?? "");
      }
    });
    return sorted;
  }, [investments, q, status, sort, performance]);

  const activeSort = SORTS.find((s) => s.key === sort)!;

  return (
    <div>
      <div className="mb-4 flex flex-col md:flex-row md:items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter positions…"
            className="pl-9"
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1 p-1 rounded-lg bg-secondary/40 border border-border/70">
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
                      layoutId="pos-status"
                      className="absolute inset-0 rounded-md bg-card ring-1 ring-border/80 shadow-sm"
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
              <span className="font-medium">{activeSort.label}</span>
            </Button>
            <AnimatePresence>
              {sortOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -4, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.97 }}
                  transition={{ duration: 0.12 }}
                  className="absolute right-0 top-full mt-1.5 w-56 rounded-lg border border-border/80 bg-card shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] p-1 z-30"
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
                        "w-full flex items-center gap-2 px-2.5 h-8 rounded-md text-xs transition-colors",
                        s.key === sort
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:text-foreground hover:bg-muted/60",
                      )}
                    >
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

      <div className="text-xs text-muted-foreground mb-3">
        {filtered.length} of {investments.length} position{investments.length === 1 ? "" : "s"}
      </div>

      <motion.div layout className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <AnimatePresence mode="popLayout">
          {filtered.map((inv) => (
            <PositionCard
              key={inv.id}
              investment={inv}
              performance={performance[inv.id]}
              onAddDistribution={onAddDistribution}
              onMarkExit={onMarkExit}
            />
          ))}
        </AnimatePresence>
      </motion.div>

      {filtered.length === 0 && (
        <div className="py-16 text-center text-sm text-muted-foreground">
          No positions match your filters.
        </div>
      )}
    </div>
  );
}
