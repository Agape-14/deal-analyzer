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
          <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Admin Review Center</div>
          <h3 className="text-base font-semibold tracking-tight">No admin review items open</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Every flagged value has been corrected, confirmed, or marked unsure for this deal.
          </p>
        </div>
      </div>
    </Card>
  );
}

export function ReviewQueueHeader({ count }: { count: number }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/70 pb-5">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-warning/15 text-warning ring-1 ring-warning/30">
          <ShieldAlert className="h-5 w-5" />
        </div>
        <div>
          <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">Admin Review Center</div>
          <h3 className="text-lg font-extrabold">
            {count} item{count === 1 ? " needs" : "s need"} review
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            Work top to bottom. Check the source when needed, correct any bad value, then confirm it or mark it unsure.
          </p>
        </div>
      </div>
    </div>
  );
}
