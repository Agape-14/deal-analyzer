"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { DeveloperCard } from "./dev-card";
import type { Developer, DealSummary } from "@/lib/types";

type SortKey = "deals" | "name" | "recent";

/** Searchable grid with a compact sort control. */
export function DeveloperGrid({
  developers,
  deals,
}: {
  developers: Developer[];
  deals: DealSummary[];
}) {
  const [q, setQ] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("deals");

  const filtered = React.useMemo(() => {
    const needle = q.trim().toLowerCase();
    let rows = developers;
    if (needle) {
      rows = rows.filter(
        (d) =>
          d.name.toLowerCase().includes(needle) ||
          d.contact_name?.toLowerCase().includes(needle) ||
          d.contact_email?.toLowerCase().includes(needle),
      );
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      switch (sort) {
        case "name":
          return a.name.localeCompare(b.name);
        case "recent":
          return (b.created_at ?? "").localeCompare(a.created_at ?? "");
        case "deals":
        default:
          return (b.deal_count ?? 0) - (a.deal_count ?? 0);
      }
    });
    return sorted;
  }, [developers, q, sort]);

  return (
    <div>
      <div className="mb-5 flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter sponsors…"
            className="pl-9"
          />
        </div>
        <div className="inline-flex items-center gap-0.5 p-1 rounded-lg bg-secondary/40 border border-border/70 text-xs">
          {[
            { key: "deals" as const, label: "Most deals" },
            { key: "name" as const, label: "Name" },
            { key: "recent" as const, label: "Recent" },
          ].map((s) => {
            const active = sort === s.key;
            return (
              <button
                key={s.key}
                onClick={() => setSort(s.key)}
                className={`relative px-2.5 h-7 rounded-md font-medium transition-colors ${
                  active ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="dev-sort"
                    className="absolute inset-0 rounded-md bg-card ring-1 ring-border/80 shadow-sm"
                    transition={{ type: "spring", stiffness: 420, damping: 32 }}
                  />
                )}
                <span className="relative">{s.label}</span>
              </button>
            );
          })}
        </div>
        <span className="text-xs text-muted-foreground ml-auto">
          {filtered.length} of {developers.length}
        </span>
      </div>

      <motion.div layout className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <AnimatePresence mode="popLayout">
          {filtered.map((dev) => (
            <DeveloperCard key={dev.id} developer={dev} deals={deals} />
          ))}
        </AnimatePresence>
      </motion.div>

      {filtered.length === 0 && (
        <div className="py-16 text-center text-sm text-muted-foreground">
          No sponsors match your search.
        </div>
      )}
    </div>
  );
}
