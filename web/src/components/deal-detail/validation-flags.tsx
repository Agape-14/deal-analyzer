"use client";

import * as React from "react";
import { AlertCircle, CheckCircle2, AlertTriangle, ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ValidationFlag } from "@/lib/types";

const SEVERITIES = [
  { key: "red", label: "Red", icon: AlertCircle, color: "text-destructive", bg: "bg-destructive/10", ring: "ring-destructive/30" },
  { key: "yellow", label: "Yellow", icon: AlertTriangle, color: "text-warning", bg: "bg-warning/10", ring: "ring-warning/30" },
  { key: "green", label: "Green", icon: CheckCircle2, color: "text-success", bg: "bg-success/10", ring: "ring-success/30" },
] as const;

/**
 * Grouped validation flags. Three severity buckets, expandable sections,
 * with per-severity counts in the header for a quick scan.
 */
export function ValidationFlagsPanel({ flags }: { flags: ValidationFlag[] | undefined }) {
  const grouped = React.useMemo(() => {
    const by: Record<string, ValidationFlag[]> = { red: [], yellow: [], green: [] };
    (flags ?? []).forEach((f) => {
      const sev = (f.severity || "").toLowerCase();
      if (sev in by) by[sev].push(f);
    });
    return by;
  }, [flags]);

  const totals = {
    red: grouped.red.length,
    yellow: grouped.yellow.length,
    green: grouped.green.length,
  };
  const total = totals.red + totals.yellow + totals.green;

  if (!flags || total === 0) {
    return (
      <Card elevated className="p-6 text-center">
        <CheckCircle2 className="h-5 w-5 text-muted-foreground mx-auto mb-2" />
        <div className="text-sm font-medium">No validation flags yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Run validation on this deal to surface red/yellow/green signals.
        </div>
      </Card>
    );
  }

  return (
    <Card elevated className="p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Validation flags</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Burke-inspired rules run over extracted metrics.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {SEVERITIES.map((s) => {
            const n = totals[s.key];
            return (
              <div
                key={s.key}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2 h-6 rounded-full text-xs font-medium",
                  s.bg,
                  s.color,
                  "ring-1",
                  s.ring,
                )}
              >
                <s.icon className="h-3 w-3" />
                {n}
              </div>
            );
          })}
        </div>
      </div>

      <div className="space-y-4">
        {SEVERITIES.map((s) => {
          const rows = grouped[s.key];
          if (rows.length === 0) return null;
          return <SeverityGroup key={s.key} severity={s} rows={rows} />;
        })}
      </div>
    </Card>
  );
}

function SeverityGroup({
  severity,
  rows,
}: {
  severity: (typeof SEVERITIES)[number];
  rows: ValidationFlag[];
}) {
  const [open, setOpen] = React.useState(severity.key !== "green");

  return (
    <div className="border border-border/60 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-muted/40 transition-colors"
      >
        <severity.icon className={cn("h-4 w-4", severity.color)} />
        <span className="text-sm font-medium flex-1 text-left">
          {rows.length} {severity.label} flag{rows.length === 1 ? "" : "s"}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 pt-1 space-y-2">
              {rows.map((f, i) => (
                <div key={i} className="text-xs flex gap-2 items-start leading-relaxed">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground border border-border/60 rounded px-1.5 py-0.5 whitespace-nowrap">
                    {f.category}
                  </span>
                  <span className="flex-1">{f.message}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
