"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Plus, Loader2, DollarSign } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Investment } from "@/lib/types";
import { cn, fmtMoney } from "@/lib/utils";

const TYPES = [
  { key: "cash_flow", label: "Cash Flow" },
  { key: "return_of_capital", label: "Return of Capital" },
  { key: "sale_proceeds", label: "Sale Proceeds" },
  { key: "refinance", label: "Refinance" },
];

export function DistributionModal({
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
    date: new Date().toISOString().slice(0, 10),
    amount: "",
    dist_type: "cash_flow",
    period: "",
    notes: "",
  });

  // Reset form when investment changes (new modal open)
  React.useEffect(() => {
    if (open && investment) {
      setForm({
        date: new Date().toISOString().slice(0, 10),
        amount: "",
        dist_type: "cash_flow",
        period: defaultPeriod(),
        notes: "",
      });
    }
  }, [open, investment]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!investment) return;
    const amount = Number(form.amount);
    if (!amount || amount <= 0) {
      toast.error("Amount must be > 0");
      return;
    }
    setSubmitting(true);
    try {
      await api.post(`/api/investments/${investment.id}/distributions`, {
        date: form.date,
        amount,
        dist_type: form.dist_type,
        period: form.period,
        notes: form.notes,
      });
      toast.success("Distribution added", {
        description: `${fmtMoney(amount)} to ${investment.project_name}`,
      });
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      toast.error("Couldn't add distribution", {
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
                <DollarSign className="h-4 w-4 text-success" />
              </div>
              <div>
                <DialogTitle>Add distribution</DialogTitle>
                <DialogDescription>
                  {investment?.project_name ? `To ${investment.project_name}` : "Record a payout"}
                </DialogDescription>
              </div>
            </div>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Amount</Label>
                <Input
                  autoFocus
                  type="number"
                  min={0}
                  step={100}
                  value={form.amount}
                  onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                  placeholder="2500"
                />
              </div>
              <div className="space-y-2">
                <Label>Date</Label>
                <Input
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Type</Label>
              <div className="flex flex-wrap gap-1.5">
                {TYPES.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, dist_type: t.key }))}
                    className={cn(
                      "px-2.5 h-7 rounded-full text-xs font-medium transition-colors",
                      form.dist_type === t.key
                        ? "bg-primary text-primary-foreground"
                        : "bg-secondary/60 text-muted-foreground hover:text-foreground hover:bg-secondary",
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Period</Label>
              <Input
                value={form.period}
                onChange={(e) => setForm((f) => ({ ...f, period: e.target.value }))}
                placeholder="Q1 2025"
              />
            </div>

            <div className="space-y-2">
              <Label>Notes</Label>
              <Input
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Optional"
              />
            </div>
          </div>

          <div className="border-t border-border/70 px-5 py-4 flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Add distribution
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function defaultPeriod() {
  const d = new Date();
  const q = Math.floor(d.getMonth() / 3) + 1;
  return `Q${q} ${d.getFullYear()}`;
}
