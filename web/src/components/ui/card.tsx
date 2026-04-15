import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Surface primitive. The "elevated" variant adds a subtle gradient + ring
 * that gives cards the premium glass/depth feel in dark mode.
 *
 * Subcomponents (CardHeader / CardTitle / CardContent / etc.) were
 * removed in the cleanup pass — every card in this codebase composes its
 * own header + body inline with the design tokens directly, which is
 * tighter than the shadcn pattern for our needs.
 */
export const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { elevated?: boolean }
>(({ className, elevated, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "rounded-xl bg-card text-card-foreground border border-border/80",
      elevated &&
        "shadow-[0_0_0_1px_hsl(var(--border))_inset,0_20px_40px_-20px_hsl(0_0%_0%/0.6)] bg-gradient-to-b from-card to-card/60",
      className,
    )}
    {...props}
  />
));
Card.displayName = "Card";
