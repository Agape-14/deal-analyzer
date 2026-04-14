"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CheckSquare, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Investment } from "@/lib/types";
import { fmtMoney, fmtMultiple } from "@/lib/utils";

/** PUTs status=exited + exit_date + exit_amount. */
export function ExitModal({
  investment,
  open,
  onOpenChange,
}: {
  investment: Investment | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [submitting, setSubmitting] = React.useState(false);
  const [form, setForm] = React.useState({
    exit_date: new Date().toISOString().slice(0, 10),
    exit_amount: "",
  });

  React.useEffect(() => {
    if (open && investment) {
      setForm({
        exit_date: new Date().toISOString().slice(0, 10),
        exit_amount: String(investment.amount_invested || ""),
      });
    }
  }, [open, investment]);

  const amount = Number(form.exit_amount) || 0;
  const implied =
    investment && investment.amount_invested > 0
      ? (amount + investment.total_distributions) / investment.amount_invested
      : null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!investment) return;
    if (amount < 0) {
      toast.error("Exit amount can't be negative");
      return;
    }
    setSubmitting(true);
    try {
      await api.put(`/api/investments/${investment.id}`, {
        status: "exited",
        exit_date: form.exit_date,
        exit_amount: amount,
      });
      toast.success("Marked exited", {
        description: `${investment.project_name} · ${fmtMoney(amount)}`,
      });
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      toast.error("Couldn't mark exit", {
        description: (err as { detail?: string })?.detail,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <div className="px-5 py-4 border-b border-border/70">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-success/10 ring-1 ring-success/30 grid place-items-center">
                <CheckSquare className="h-4 w-4 text-success" />
              </div>
              <div>
                <DialogTitle>Mark as exited</DialogTitle>
                <DialogDescription>
                  {investment?.project_name ? `Record the exit for ${investment.project_name}` : "Close out a position"}
                </DialogDescription>
              </div>
            </div>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Exit amount</Label>
                <Input
                  autoFocus
                  type="number"
                  min={0}
                  step={1000}
                  value={form.exit_amount}
                  onChange={(e) => setForm((f) => ({ ...f, exit_amount: e.target.value }))}
                  placeholder="0"
                />
              </div>
              <div className="space-y-2">
                <Label>Exit date</Label>
                <Input
                  type="date"
                  value={form.exit_date}
                  onChange={(e) => setForm((f) => ({ ...f, exit_date: e.target.value }))}
                />
              </div>
            </div>

            {investment && (
              <div className="rounded-lg border border-border/60 p-3 bg-muted/30 text-xs space-y-1">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Invested</span>
                  <span className="tabular-nums font-medium">{fmtMoney(investment.amount_invested)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Distributions to date</span>
                  <span className="tabular-nums font-medium">{fmtMoney(investment.total_distributions)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Exit proceeds</span>
                  <span className="tabular-nums font-medium">{fmtMoney(amount)}</span>
                </div>
                <div className="flex justify-between pt-1 border-t border-border/60">
                  <span className="text-foreground font-medium">Implied multiple</span>
                  <span className="tabular-nums font-semibold text-primary">
                    {implied != null ? fmtMultiple(implied) : "—"}
                  </span>
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-border/70 px-5 py-4 flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckSquare className="h-4 w-4" />}
              Mark exited
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
