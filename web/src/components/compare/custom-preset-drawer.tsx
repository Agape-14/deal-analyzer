"use client";

import * as React from "react";
import { Check, Sparkles, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogSheet, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ALL_ROWS, PRESETS, type MetricRow } from "./presets";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "compare.custom-preset";

export function readCustomPreset(): string[] | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((x) => typeof x === "string")) return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

/** Group metric rows by row.group for a tidy checkbox list. */
function groupRows(rows: MetricRow[]): Array<{ group: string; rows: MetricRow[] }> {
  const map = new Map<string, MetricRow[]>();
  for (const r of rows) {
    if (!map.has(r.group)) map.set(r.group, []);
    map.get(r.group)!.push(r);
  }
  return [...map.entries()].map(([group, rows]) => ({ group, rows }));
}

/**
 * Build Your Own: checkbox list over every known metric, grouped by
 * category. Selection persists in localStorage so every subsequent visit
 * re-loads it.
 */
export function CustomPresetDrawer({
  open,
  onOpenChange,
  onApply,
  initialKeys,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (keys: string[]) => void;
  initialKeys: string[];
}) {
  const [picked, setPicked] = React.useState<Set<string>>(new Set(initialKeys));

  React.useEffect(() => {
    if (open) setPicked(new Set(initialKeys));
  }, [open, initialKeys]);

  const groups = React.useMemo(() => groupRows(ALL_ROWS), []);

  function togglePresetSeed(key: string) {
    const p = PRESETS.find((x) => x.key === key);
    if (!p) return;
    setPicked(new Set(p.rows.map((r) => r.key)));
  }

  function toggleRow(key: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleGroup(keys: string[]) {
    setPicked((prev) => {
      const next = new Set(prev);
      const allIn = keys.every((k) => next.has(k));
      if (allIn) keys.forEach((k) => next.delete(k));
      else keys.forEach((k) => next.add(k));
      return next;
    });
  }

  function save() {
    const ordered = ALL_ROWS.map((r) => r.key).filter((k) => picked.has(k));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ordered));
    } catch {
      /* ignore */
    }
    onApply(ordered);
    toast.success("Custom preset saved", { description: `${ordered.length} metrics.` });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogSheet>
        <div className="px-6 pt-6 pb-4 border-b border-border/70">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-primary/10 ring-1 ring-primary/30 grid place-items-center">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <div>
              <DialogTitle>Build your own preset</DialogTitle>
              <DialogDescription>
                Pick exactly the rows you care about. Saved to this browser.
              </DialogDescription>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mr-1">
              Seed from:
            </span>
            {PRESETS.filter((p) => p.key !== "all").map((p) => (
              <button
                key={p.key}
                onClick={() => togglePresetSeed(p.key)}
                className="px-2.5 h-7 rounded-full text-xs font-medium bg-secondary/60 hover:bg-secondary text-foreground transition-colors"
              >
                {p.label}
              </button>
            ))}
            <button
              onClick={() => setPicked(new Set())}
              className="inline-flex items-center gap-1 px-2.5 h-7 rounded-full text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              <RotateCcw className="h-3 w-3" />
              Clear
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {groups.map(({ group, rows }) => {
            const keys = rows.map((r) => r.key);
            const allIn = keys.every((k) => picked.has(k));
            const partial = !allIn && keys.some((k) => picked.has(k));
            return (
              <div key={group} className="py-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground font-semibold">
                    {group}
                  </h3>
                  <button
                    onClick={() => toggleGroup(keys)}
                    className={cn(
                      "text-[10px] uppercase tracking-wider font-medium transition-colors",
                      allIn ? "text-primary" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {allIn ? "Deselect all" : partial ? "Select all" : "Select all"}
                  </button>
                </div>
                <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
                  {rows.map((r) => {
                    const isSelected = picked.has(r.key);
                    return (
                      <button
                        key={r.key}
                        onClick={() => toggleRow(r.key)}
                        className={cn(
                          "flex items-center gap-2 py-1.5 rounded-md text-left transition-colors",
                          isSelected ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        <span
                          className={cn(
                            "h-4 w-4 rounded border grid place-items-center shrink-0 transition-colors",
                            isSelected ? "bg-primary border-primary text-primary-foreground" : "border-border",
                          )}
                        >
                          {isSelected && <Check className="h-2.5 w-2.5" />}
                        </span>
                        <span className="text-sm flex-1 truncate">{r.label}</span>
                        {r.direction !== "none" && (
                          <span className="text-[9px] uppercase tracking-wider text-muted-foreground shrink-0">
                            {r.direction === "higher" ? "▲" : "▼"}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div className="border-t border-border/70 px-6 py-4 flex items-center justify-between gap-2 bg-background/40">
          <span className="text-xs text-muted-foreground">{picked.size} rows selected</span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={picked.size === 0}>
              <Save className="h-4 w-4" />
              Save preset
            </Button>
          </div>
        </div>
      </DialogSheet>
    </Dialog>
  );
}
