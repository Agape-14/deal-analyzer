"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/auth-client";
import { fmtDate, fmtMoney } from "@/lib/utils";
import type { Distribution, Investment } from "@/lib/types";
import { DistributionModal } from "./distribution-modal";

export function DistributionLedger({ investment }: { investment: Investment }) {
  const router = useRouter();
  const { isAnalyst, loading } = useCurrentUser();
  const [editing, setEditing] = React.useState<Distribution | null>(null);
  const [busy, setBusy] = React.useState<number | null>(null);
  const [showRemoved, setShowRemoved] = React.useState(false);
  const inFlight = React.useRef(false);
  const ledger = investment.distribution_ledger ?? investment.distributions;
  const removed = ledger.filter(row => row.deleted_at);
  const rows = showRemoved ? ledger : ledger.filter(row => !row.deleted_at);

  async function restore(id: number, revision?: number) {
    await api.post(`/api/investments/${investment.id}/distributions/${id}/restore`, { expected_revision: revision });
    router.refresh();
  }

  async function change(row: Distribution) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(row.id);
    try {
      if (row.deleted_at) {
        await restore(row.id, row.revision);
        toast.success("Distribution restored");
      } else {
        const result = await api.delete<{ revision: number }>(`/api/investments/${investment.id}/distributions/${row.id}${row.revision ? `?expected_revision=${row.revision}` : ""}`);
        toast.success("Distribution removed", { duration: 8000, description: "Payment history is retained.", action: {
          label: "Undo payment removal", onClick: async () => {
            try { await restore(row.id, result.revision); toast.success("Distribution restored"); }
            catch (error) { toast.error("Couldn't restore distribution", { description: (error as { detail?: string }).detail }); }
          },
        } });
        router.refresh();
      }
    } catch (error) {
      toast.error("Couldn't change distribution", { description: (error as { detail?: string }).detail });
      router.refresh();
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  return <>
    <details className="mt-4 border-t border-border/50 pt-3 text-xs" data-testid="distribution-ledger">
      <summary className="cursor-pointer font-medium">Payment history ({investment.distributions.length})</summary>
      {removed.length > 0 && <label className="my-3 flex items-center gap-2"><input type="checkbox" checked={showRemoved} onChange={event => setShowRemoved(event.target.checked)} />Show removed payments ({removed.length})</label>}
      {!rows.length && <p className="my-3 text-muted-foreground">No distributions recorded.</p>}
      <div className="mt-3 space-y-3">{rows.map(row => <div key={row.id} className="rounded-md border border-border/60 p-3" data-testid={`distribution-${row.id}`}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="font-medium">{fmtMoney(row.amount)} · {row.date ? fmtDate(row.date) : "Date unavailable"}{row.deleted_at && <span className="ml-2 text-muted-foreground">Removed</span>}</p>
          {!loading && isAnalyst && <div className="flex gap-3">
            {!row.deleted_at && <button type="button" className="underline" disabled={busy !== null} onClick={() => setEditing(row)}>Edit payment</button>}
            <button type="button" className="underline" disabled={busy !== null} onClick={() => change(row)}>{busy === row.id ? "Saving…" : row.deleted_at ? "Restore payment" : "Remove payment"}</button>
          </div>}
        </div>
        <p className="mt-1 text-muted-foreground">{row.dist_type.replaceAll("_", " ")}{row.period && ` · ${row.period}`}</p>
        {row.notes && <p className="mt-1 whitespace-pre-wrap break-words">{row.notes}</p>}
        {!!row.history?.length && <details className="mt-2 text-muted-foreground"><summary className="cursor-pointer">Change history ({row.history.length})</summary><ul className="mt-2 space-y-1">{row.history.map(event => <li key={event.revision}>Revision {event.revision} {event.action} · {fmtDate(event.recorded_at)} · previously {fmtMoney(Number(event.previous.amount ?? 0))} on {String(event.previous.date ?? "unknown date")}</li>)}</ul></details>}
      </div>)}</div>
    </details>
    <DistributionModal investment={investment} distribution={editing} open={editing !== null} onOpenChange={open => { if (!open) setEditing(null); }} />
  </>;
}
