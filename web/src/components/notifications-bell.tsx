"use client";

import * as React from "react";
import Link from "next/link";
import {
  Bell,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Info,
  CheckCheck,
  Sparkles,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn, fmtDate } from "@/lib/utils";

interface Notification {
  id: number;
  kind: string;
  title: string;
  body: string;
  href: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

/**
 * Header bell + dropdown. Polls /api/notifications/unread-count every
 * 45 seconds; fetches the full list only when the dropdown opens.
 *
 * Fails silently if the endpoint 401s (user signed out in another tab)
 * or 5xxs — the bell just stays dim until the backend recovers.
 */
export function NotificationsBell() {
  const [open, setOpen] = React.useState(false);
  const [unread, setUnread] = React.useState(0);
  const [items, setItems] = React.useState<Notification[] | null>(null);
  const [loading, setLoading] = React.useState(false);

  // Background poll for unread count
  React.useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const r = await fetch("/api/notifications/unread-count", { credentials: "include" });
        if (!r.ok) return;
        const d = (await r.json()) as { unread: number };
        if (!cancelled) setUnread(d.unread);
      } catch {
        /* ignore */
      }
    }

    void tick();
    const t = window.setInterval(tick, 45_000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  // Load list on open
  async function loadItems() {
    setLoading(true);
    try {
      const r = await fetch("/api/notifications?limit=30", { credentials: "include" });
      if (!r.ok) throw new Error(String(r.status));
      const d = (await r.json()) as { items: Notification[]; unread: number };
      setItems(d.items);
      setUnread(d.unread);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    if (open && items === null) void loadItems();
  }, [open, items]);

  async function markAll() {
    try {
      await fetch("/api/notifications/mark-read", {
        method: "POST",
        credentials: "include",
      });
      setUnread(0);
      setItems((prev) =>
        prev
          ? prev.map((n) =>
              n.read_at ? n : { ...n, read_at: new Date().toISOString() },
            )
          : prev,
      );
    } catch {
      /* ignore */
    }
  }

  async function markOne(id: number) {
    try {
      await fetch(`/api/notifications/${id}/mark-read`, {
        method: "POST",
        credentials: "include",
      });
      setItems((prev) =>
        prev
          ? prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n))
          : prev,
      );
      setUnread((c) => Math.max(0, c - 1));
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Notifications"
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 180)}
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute top-1.5 right-1.5 inline-flex items-center justify-center min-w-3.5 h-3.5 px-1 rounded-full bg-primary text-[9px] font-semibold text-primary-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.12 }}
            className="absolute right-0 top-full mt-1.5 w-[22rem] rounded-lg border border-border/80 bg-card shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] z-30 overflow-hidden"
            // Keep the dropdown open while the mouse is inside, even when
            // the trigger button loses focus.
            onMouseDown={(e) => e.preventDefault()}
          >
            <div className="flex items-center justify-between px-3.5 py-2 border-b border-border/70">
              <div className="text-sm font-semibold">Notifications</div>
              <button
                onClick={markAll}
                disabled={unread === 0}
                className={cn(
                  "inline-flex items-center gap-1 text-[11px] font-medium transition-colors",
                  unread === 0
                    ? "text-muted-foreground cursor-default"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <CheckCheck className="h-3 w-3" />
                Mark all read
              </button>
            </div>

            <div className="max-h-[60vh] overflow-y-auto">
              {loading && items === null ? (
                <div className="p-6 text-center text-xs text-muted-foreground">Loading…</div>
              ) : !items || items.length === 0 ? (
                <div className="p-8 text-center">
                  <Sparkles className="h-5 w-5 text-muted-foreground mx-auto mb-2" />
                  <div className="text-sm font-medium">You're all caught up</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    We'll ping you here when extraction / verification finishes.
                  </div>
                </div>
              ) : (
                <ul className="divide-y divide-border/50">
                  {items.map((n) => (
                    <NotificationRow key={n.id} n={n} onMarkRead={markOne} />
                  ))}
                </ul>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NotificationRow({
  n,
  onMarkRead,
}: {
  n: Notification;
  onMarkRead: (id: number) => void;
}) {
  const Icon = iconFor(n.kind);
  const color = colorFor(n.kind);
  const isUnread = !n.read_at;

  const body = (
    <>
      <div className="flex items-start gap-2.5">
        <div className={cn("mt-0.5 h-6 w-6 rounded-full grid place-items-center shrink-0", color.bg)}>
          <Icon className={cn("h-3 w-3", color.fg)} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="text-sm font-medium leading-tight truncate">{n.title}</div>
            {isUnread && <span className="shrink-0 h-1.5 w-1.5 rounded-full bg-primary mt-1.5" />}
          </div>
          {n.body && (
            <div className="text-[11px] text-muted-foreground mt-1 line-clamp-2">{n.body}</div>
          )}
          <div className="text-[10px] text-muted-foreground mt-1">{fmtDate(n.created_at)}</div>
        </div>
      </div>
    </>
  );

  return (
    <li
      className={cn(
        "p-3 hover:bg-muted/40 transition-colors",
        !isUnread && "opacity-70",
      )}
    >
      {n.href ? (
        <Link href={n.href} onClick={() => onMarkRead(n.id)} className="block">
          {body}
        </Link>
      ) : (
        <button onClick={() => onMarkRead(n.id)} className="w-full text-left">
          {body}
        </button>
      )}
    </li>
  );
}

function iconFor(kind: string) {
  switch (kind) {
    case "success":
      return CheckCircle2;
    case "warning":
      return AlertTriangle;
    case "error":
      return AlertCircle;
    default:
      return Info;
  }
}

function colorFor(kind: string) {
  switch (kind) {
    case "success":
      return { bg: "bg-success/15", fg: "text-success" };
    case "warning":
      return { bg: "bg-warning/15", fg: "text-warning" };
    case "error":
      return { bg: "bg-destructive/15", fg: "text-destructive" };
    default:
      return { bg: "bg-primary/15", fg: "text-primary" };
  }
}
