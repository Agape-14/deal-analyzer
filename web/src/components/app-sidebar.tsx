"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  GitCompareArrows,
  Building2,
  Wallet,
  Sparkles,
  Menu,
  X,
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

/**
 * Shared nav list rendered in both the desktop sidebar and the mobile
 * drawer. The `layoutId="sidebar-active"` indicator animates between
 * items as the route changes, in both form factors.
 */
function NavList({ onPick }: { onPick?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="space-y-0.5">
      {NAV.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onPick}
              className={cn(
                "relative group flex items-center gap-3 px-3 h-9 rounded-md text-sm transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
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
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-5 h-16 border-b border-border/60">
      <div className="relative h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-chart-3 shadow-[0_8px_24px_-8px_hsl(var(--primary)/.6)] grid place-items-center">
        <Sparkles className="h-4 w-4 text-primary-foreground" />
      </div>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-tight">Kenyon</div>
        <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Deal Analyzer</div>
      </div>
    </Link>
  );
}

function LegacyLink({ onPick }: { onPick?: () => void }) {
  return (
    <Link
      href="/legacy"
      onClick={onPick}
      className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
    >
      Switch to legacy UI →
    </Link>
  );
}

function UserMenu({ onPick }: { onPick?: () => void }) {
  const [user, setUser] = React.useState<{ username?: string; authenticated: boolean } | null>(null);
  React.useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setUser(d))
      .catch(() => setUser(null));
  }, []);

  if (!user?.authenticated) return null;

  async function signOut() {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {
      /* ignore */
    }
    onPick?.();
    window.location.href = "/login";
  }

  return (
    <div className="flex items-center justify-between gap-2">
      <div className="text-[11px] text-muted-foreground truncate">
        Signed in as <span className="text-foreground font-medium">{user.username || "user"}</span>
      </div>
      <button
        onClick={signOut}
        className="text-[11px] text-muted-foreground hover:text-destructive transition-colors"
      >
        Sign out
      </button>
    </div>
  );
}

/** Desktop sidebar (md+). */
export function AppSidebar() {
  return (
    <aside className="hidden md:flex fixed inset-y-0 left-0 w-60 flex-col border-r border-border/80 bg-background/95 z-40">
      <Brand />
      <nav className="flex-1 p-3">
        <NavList />
      </nav>
      <div className="px-5 py-3 border-t border-border/60 space-y-2">
        <UserMenu />
        <LegacyLink />
      </div>
    </aside>
  );
}

/**
 * Mobile sidebar: hidden on md+, renders a hamburger button that opens
 * a slide-in drawer with the same NavList. Closes on nav-item click,
 * escape key, or backdrop tap.
 */
export function MobileNav() {
  const [open, setOpen] = React.useState(false);
  const pathname = usePathname();

  // Close on route change
  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Esc to close
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <button
        type="button"
        aria-label="Open navigation"
        onClick={() => setOpen(true)}
        className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-muted/60 transition-colors"
      >
        <Menu className="h-5 w-5" />
      </button>

      <AnimatePresence>
        {open && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={() => setOpen(false)}
              className="md:hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
            />
            {/* Drawer */}
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", stiffness: 380, damping: 34 }}
              className="md:hidden fixed inset-y-0 left-0 z-50 w-64 bg-background border-r border-border/80 flex flex-col"
            >
              <div className="flex items-center justify-between border-b border-border/60">
                <Brand />
                <button
                  type="button"
                  aria-label="Close navigation"
                  onClick={() => setOpen(false)}
                  className="mr-2 h-9 w-9 grid place-items-center rounded-md hover:bg-muted/60 transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <nav className="flex-1 p-3">
                <NavList onPick={() => setOpen(false)} />
              </nav>
              <div className="px-5 py-3 border-t border-border/60 space-y-2">
                <UserMenu onPick={() => setOpen(false)} />
                <LegacyLink onPick={() => setOpen(false)} />
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
