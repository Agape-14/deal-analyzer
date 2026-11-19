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
import type { Distribution, Investment } from "@/lib/types";
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
  distribution = null,
}: {
  investment: Investment | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  distribution?: Distribution | null;
}) {
  const router = useRouter();
  const [submitting, setSubmitting] = React.useState(false);
  const requestId = React.useRef("");
  const inFlight = React.useRef(false);
  const editing = distribution !== null;
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
      requestId.current = crypto.randomUUID();
      setForm({
        date: distribution?.date ?? new Date().toISOString().slice(0, 10),
        amount: distribution ? String(distribution.amount) : "",
        dist_type: distribution?.dist_type ?? "cash_flow",
        period: distribution?.period ?? defaultPeriod(),
        notes: distribution?.notes ?? "",
      });
    }
  }, [open, investment?.id, distribution?.id, distribution?.revision]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!investment || inFlight.current) return;
    const amount = Number(form.amount);
    if (!amount || amount <= 0) {
      toast.error("Amount must be > 0");
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    try {
      const payload = {
        date: form.date,
        amount,
        dist_type: form.dist_type,
        period: form.period,
        notes: form.notes,
      };
      let replayed = false;
      let removed = false;
      if (distribution) await api.put(`/api/investments/${investment.id}/distributions/${distribution.id}`, { ...payload, expected_revision: distribution.revision });
      else {
        const saved = await api.post<{ replayed?: boolean; removed?: boolean }>(`/api/investments/${investment.id}/distributions`, { ...payload, request_id: requestId.current });
        replayed = saved.replayed ?? false;
        removed = saved.removed ?? false;
      }
      toast.success(replayed ? "Distribution already recorded" : editing ? "Distribution updated" : "Distribution added", {
        description: replayed ? removed ? "This payment was removed. Use payment history to restore it if needed." : "Payment history shows its current details." : `${fmtMoney(amount)} to ${investment.project_name}`,
      });
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      toast.error(editing ? "Couldn't update distribution" : "Couldn't add distribution", {
        description: (err as { detail?: string })?.detail,
      });
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={value => { if (!inFlight.current) onOpenChange(value); }}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit}>
          <div className="px-5 py-4 border-b border-border/70">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-success/10 ring-1 ring-success/30 grid place-items-center">
                <DollarSign className="h-4 w-4 text-success" />
              </div>
              <div>
                <DialogTitle>{editing ? "Edit distribution" : "Add distribution"}</DialogTitle>
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
                <Input aria-label="Amount"
                  autoFocus
                  type="number"
                  min={0.01}
                  step={0.01}
                  required
                  value={form.amount}
                  onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                  placeholder="2500"
                />
              </div>
              <div className="space-y-2">
                <Label>Date</Label>
                <Input aria-label="Distribution date"
                  type="date"
                  required
                  min={investment?.investment_date ?? undefined}
                  max={investment?.status === "exited" && investment.exit_date ? investment.exit_date : new Date().toISOString().slice(0, 10)}
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
              <Input aria-label="Distribution period"
                value={form.period}
                onChange={(e) => setForm((f) => ({ ...f, period: e.target.value }))}
                placeholder="Q1 2025"
              />
            </div>

            <div className="space-y-2">
              <Label>Notes</Label>
              <Input aria-label="Distribution notes"
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
              {editing ? "Save distribution" : "Add distribution"}
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
