"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex items-center gap-1 border-b border-border/70 h-11",
      className,
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

/**
 * Tab trigger with an animated underline (layoutId) that glides between
 * active tabs — feels similar to Linear / Vercel's active nav indicator.
 */
export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> & {
    indicatorId?: string;
  }
>(({ className, children, indicatorId = "tabs-active", ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "relative inline-flex items-center gap-2 h-11 px-3 text-sm font-medium",
      "text-muted-foreground hover:text-foreground transition-colors",
      "data-[state=active]:text-foreground",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md",
      className,
    )}
    {...props}
  >
    <span className="relative z-10 flex items-center gap-2">{children}</span>
    <ActiveUnderline indicatorId={indicatorId} />
  </TabsPrimitive.Trigger>
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

function ActiveUnderline({ indicatorId }: { indicatorId: string }) {
  // Rendered only on active; Radix sets data-state="active" on the trigger.
  return (
    <motion.span
      aria-hidden
      layoutId={indicatorId}
      className="absolute -bottom-px left-0 right-0 h-0.5 bg-primary rounded-full opacity-0 [[data-state=active]_&]:opacity-100"
      transition={{ type: "spring", stiffness: 500, damping: 36 }}
    />
  );
}

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-6 focus-visible:outline-none data-[state=active]:animate-in data-[state=active]:fade-in-50",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;
