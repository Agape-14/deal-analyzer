"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Inline "which document is right?" picker. Shown only when a field has
 * conflicting values across documents. POSTs to
 * /api/deals/{id}/fields/resolve-conflict which locks the picked value so
 * future re-extractions won't overwrite it.
 */
export function ConflictPicker({
  dealId,
  path,
  conflict,
  currentValue,
}: {
  dealId: number;
  path: string;
  conflict: Array<{ doc_id: number; doc_name: string; value: unknown }>;
  currentValue: unknown;
}) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  async function pick(value: unknown) {
    setBusy(true);
    try {
      await api.post(`/api/deals/${dealId}/fields/resolve-conflict`, { path, value });
      toast.success("Conflict resolved", { description: `${path} locked to ${String(value)}` });
      setOpen(false);
      router.refresh();
    } catch (err) {
      toast.error("Couldn't resolve", { description: (err as { detail?: string })?.detail });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 160)}
        className="inline-flex items-center gap-1 px-1.5 h-5 rounded-full bg-destructive/15 text-destructive ring-1 ring-destructive/30 text-[10px] font-medium hover:bg-destructive/25 transition-colors"
      >
        <AlertTriangle className="h-2.5 w-2.5" />
        Resolve
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.96 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 top-full mt-1 w-64 rounded-lg border border-border/80 bg-popover shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] z-50 p-1.5"
          >
            <div className="px-2 pt-1 pb-1.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Which value is correct?
            </div>
            {conflict.map((c, i) => {
              const isCurrent =
                c.value === currentValue ||
                (typeof c.value === "number" && typeof currentValue === "number" && Math.abs(c.value - currentValue) < 1e-6);
              return (
                <button
                  key={i}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    if (!busy) pick(c.value);
                  }}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs hover:bg-muted/60 transition-colors text-left",
                    isCurrent && "bg-primary/5",
                  )}
                  disabled={busy}
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-medium truncate">{c.doc_name}</div>
                    <div className="text-[10px] text-muted-foreground tabular-nums">
                      {String(c.value)}
                      {isCurrent && " (current)"}
                    </div>
                  </div>
                  {busy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
                  ) : isCurrent ? (
                    <Check className="h-3.5 w-3.5 text-primary shrink-0" />
                  ) : null}
                </button>
              );
            })}
            <div className="px-2 pt-1 pb-0.5 text-[10px] text-muted-foreground border-t border-border/60 mt-1">
              Picking locks the field against future re-extractions.
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
