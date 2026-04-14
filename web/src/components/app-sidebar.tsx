"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  GitCompareArrows,
  Building2,
  Wallet,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV: Array<{
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}> = [
  { href: "/", label: "Deals", icon: LayoutDashboard },
  { href: "/compare", label: "Compare", icon: GitCompareArrows },
  { href: "/developers", label: "Developers", icon: Building2 },
  { href: "/portfolio", label: "Portfolio", icon: Wallet },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex fixed inset-y-0 left-0 w-60 flex-col border-r border-border/80 bg-background/95 z-40">
      {/* Brand */}
      <Link href="/" className="flex items-center gap-2.5 px-5 h-16 border-b border-border/60">
        <div className="relative h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-chart-3 shadow-[0_8px_24px_-8px_hsl(var(--primary)/.6)] grid place-items-center">
          <Sparkles className="h-4 w-4 text-primary-foreground" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">Kenyon</div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Deal Analyzer</div>
        </div>
      </Link>

      {/* Nav */}
      <nav className="flex-1 p-3">
        <ul className="space-y-0.5">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "relative group flex items-center gap-3 px-3 h-9 rounded-md text-sm transition-colors",
                    active
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="sidebar-active"
                      className="absolute inset-0 rounded-md bg-muted/60 ring-1 ring-border/70"
                      transition={{ type: "spring", stiffness: 500, damping: 36 }}
                    />
                  )}
                  <item.icon className="relative h-4 w-4" />
                  <span className="relative font-medium">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border/60">
        <Link
          href="/legacy"
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Switch to legacy UI →
        </Link>
      </div>
    </aside>
  );
}
