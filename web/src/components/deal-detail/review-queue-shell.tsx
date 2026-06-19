import { CheckCircle2, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";

export function ReviewQueueEmptyState() {
  return (
    <Card elevated className="p-6">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-success/15 text-success ring-1 ring-success/30">
          <CheckCircle2 className="h-5 w-5" />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Deal Readiness</div>
          <h3 className="text-base font-semibold tracking-tight">Ready to score</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Every open review item has been corrected or confirmed.</p>
        </div>
      </div>
    </Card>
  );
}

export function ReviewQueueHeader({ visibleCount, hiddenCount }: { visibleCount: number; hiddenCount: number }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-destructive/15 text-destructive ring-1 ring-destructive/30">
          <ShieldAlert className="h-5 w-5" />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Deal Readiness</div>
          <h3 className="text-base font-semibold tracking-tight">Needs review</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {visibleCount} priority item{visibleCount === 1 ? "" : "s"} shown. Review the source, fix the inputs, or confirm the item to clear it.
          </p>
        </div>
      </div>
      {hiddenCount > 0 ? (
        <a href="#technical-details" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
          {hiddenCount} more grouped below
        </a>
      ) : null}
    </div>
  );
}

export function ReviewQueueSteps() {
  return (
    <div className="mt-5 grid gap-2 sm:grid-cols-3">
      <ActionHint label="1. Inspect" detail="Open the cited evidence for the row." />
      <ActionHint label="2. Correct" detail="Edit any value that is wrong." />
      <ActionHint label="3. Clear" detail="Confirm when the item is acceptable." />
    </div>
  );
}

function ActionHint({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2">
      <div className="text-xs font-semibold tracking-tight text-foreground">{label}</div>
      <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{detail}</div>
    </div>
  );
}
