import { CheckCircle2, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";

export function ReviewQueueEmptyState() {
  return (
    <Card className="border-border/80 bg-card p-6 shadow-sm">
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
  const total = visibleCount + hiddenCount;
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/70 pb-5">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-warning/15 text-warning ring-1 ring-warning/30">
          <ShieldAlert className="h-5 w-5" />
        </div>
        <div>
          <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">Deal Readiness</div>
          <h3 className="text-lg font-extrabold">
            {total} item{total === 1 ? "" : "s"} need review
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            Work these like an analyst checklist: inspect the source, correct any bad value, then confirm to clear the item.
          </p>
        </div>
      </div>
      {hiddenCount > 0 ? (
        <a href="#technical-details" className="rounded-full border border-border/70 bg-background px-3 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground">
          {hiddenCount} more grouped below
        </a>
      ) : null}
    </div>
  );
}

export function ReviewQueueSteps() {
  return (
    <div className="mt-5 grid overflow-hidden rounded-xl border border-border/80 bg-background sm:grid-cols-3">
      <ActionHint label="1. Inspect" detail="Open the exact source evidence." />
      <ActionHint label="2. Correct" detail="Edit only values that are wrong." />
      <ActionHint label="3. Confirm" detail="Clear the row when it is acceptable." />
    </div>
  );
}

function ActionHint({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="border-b border-border/70 px-4 py-3 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <div className="text-xs font-extrabold text-foreground">{label}</div>
      <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{detail}</div>
    </div>
  );
}
