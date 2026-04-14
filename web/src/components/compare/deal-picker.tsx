"use client";

import * as React from "react";
import { Search, Check, Plus } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn, fmtPct, fmtMultiple } from "@/lib/utils";
import type { DealSummary } from "@/lib/types";

/**
 * Deal picker sheet. Multi-select with a search box. "Apply" returns the
 * new set of selected ids — parent handles the URL/data side.
 */
export function DealPicker({
  open,
  onOpenChange,
  deals,
  selected,
  onApply,
  max = 6,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deals: DealSummary[];
  selected: number[];
  onApply: (ids: number[]) => void;
  max?: number;
}) {
  const [q, setQ] = React.useState("");
  const [pick, setPick] = React.useState<Set<number>>(new Set(selected));

  // Sync selection when modal opens with fresh `selected`
  React.useEffect(() => {
    if (open) setPick(new Set(selected));
  }, [open, selected]);

  const filtered = React.useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return deals;
    return deals.filter(
      (d) =>
        d.project_name.toLowerCase().includes(needle) ||
        d.developer_name.toLowerCase().includes(needle) ||
        d.city.toLowerCase().includes(needle),
    );
  }, [deals, q]);

  function toggle(id: number) {
    setPick((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (next.size >= max) return prev;
        next.add(id);
      }
      return next;
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-border/70">
          <DialogTitle>Pick deals to compare</DialogTitle>
          <DialogDescription>
            Select up to {max} deals. Unselected deals stay in your pipeline.
          </DialogDescription>
          <div className="relative mt-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <Input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search project, sponsor, city…"
              className="pl-9"
            />
          </div>
        </div>

        <div className="max-h-[50vh] overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">No deals match.</div>
          ) : (
            <ul className="divide-y divide-border/60">
              {filtered.map((d) => {
                const isSelected = pick.has(d.id);
                return (
                  <li key={d.id}>
                    <button
                      onClick={() => toggle(d.id)}
                      className={cn(
                        "w-full flex items-center gap-3 px-5 py-3 hover:bg-muted/40 transition-colors text-left",
                        isSelected && "bg-primary/5",
                      )}
                    >
                      <span
                        className={cn(
                          "h-5 w-5 rounded-md border grid place-items-center shrink-0 transition-colors",
                          isSelected
                            ? "bg-primary border-primary text-primary-foreground"
                            : "border-border",
                        )}
                      >
                        {isSelected && <Check className="h-3 w-3" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">{d.project_name}</div>
                        <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
                          {[d.city, d.state].filter(Boolean).join(", ") || "—"}
                          {d.developer_name && (
                            <>
                              <span className="mx-1.5 opacity-40">·</span>
                              {d.developer_name}
                            </>
                          )}
                        </div>
                      </div>
                      <div className="text-right shrink-0 text-xs tabular-nums">
                        <div className="font-semibold">
                          {d.overall_score != null ? d.overall_score.toFixed(1) : "—"}
                          <span className="text-muted-foreground font-normal"> · score</span>
                        </div>
                        <div className="text-muted-foreground mt-0.5">
                          {fmtPct(d.target_irr)} · {fmtMultiple(d.target_equity_multiple)}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-border/70 px-5 py-3">
          <span className="text-xs text-muted-foreground">
            {pick.size} of {max} selected
          </span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => {
                onApply([...pick]);
                onOpenChange(false);
              }}
              disabled={pick.size === 0}
            >
              <Plus className="h-4 w-4" />
              Compare {pick.size ? `(${pick.size})` : ""}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
