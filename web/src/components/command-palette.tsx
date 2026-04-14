"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import {
  LayoutDashboard,
  GitCompareArrows,
  Building2,
  Wallet,
  Plus,
  Building,
  User,
  Search,
  ArrowRight,
} from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { DealSummary, Developer } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Global command palette. Opens on ⌘K / Ctrl+K, or on the custom event the
 * header button dispatches. Fetches deals + developers once per open, then
 * filters client-side via cmdk's built-in fuzzy ranking.
 *
 * Results section is intentionally small — the palette should feel like a
 * precision tool, not a search engine.
 */
export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [deals, setDeals] = React.useState<DealSummary[] | null>(null);
  const [developers, setDevelopers] = React.useState<Developer[] | null>(null);
  const [loading, setLoading] = React.useState(false);

  // Global keybinding
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    function onOpen() {
      setOpen(true);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("open-command-palette", onOpen);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("open-command-palette", onOpen);
    };
  }, []);

  // Lazy-load data the first time it's opened, re-use after that. We treat
  // the palette as a read-through cache — for now, simple is fine.
  React.useEffect(() => {
    if (!open || deals !== null || loading) return;
    setLoading(true);
    Promise.all([
      api.get<DealSummary[]>("/api/deals").catch(() => [] as DealSummary[]),
      api.get<Developer[]>("/api/developers").catch(() => [] as Developer[]),
    ])
      .then(([d, dev]) => {
        setDeals(d);
        setDevelopers(dev);
      })
      .finally(() => setLoading(false));
  }, [open, deals, loading]);

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent hideClose className="max-w-xl p-0 overflow-hidden">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command
          label="Command palette"
          className="flex flex-col max-h-[60vh]"
          // cmdk defaults to its own fuzzy filter; that's what we want
        >
          <div className="flex items-center gap-2.5 px-4 h-12 border-b border-border/80">
            <Search className="h-4 w-4 text-muted-foreground shrink-0" />
            <Command.Input
              placeholder="Search deals, developers, actions…"
              className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
              autoFocus
            />
            <kbd className="hidden sm:inline-flex items-center text-[10px] font-mono text-muted-foreground border border-border/80 rounded px-1.5 py-0.5">
              esc
            </kbd>
          </div>

          <Command.List className="overflow-y-auto py-2 px-1.5">
            <Command.Empty className="px-3 py-8 text-center text-sm text-muted-foreground">
              {loading ? "Searching…" : "Nothing found."}
            </Command.Empty>

            <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground">
              <Item icon={Plus} onSelect={() => go("/?new=1")}>
                New deal
              </Item>
              <Item icon={LayoutDashboard} onSelect={() => go("/")}>
                Go to deals
              </Item>
              <Item icon={GitCompareArrows} onSelect={() => go("/compare")}>
                Compare deals
              </Item>
              <Item icon={Building2} onSelect={() => go("/developers")}>
                View developers
              </Item>
              <Item icon={Wallet} onSelect={() => go("/portfolio")}>
                View portfolio
              </Item>
            </Command.Group>

            {deals && deals.length > 0 && (
              <Command.Group heading="Deals" className="mt-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground">
                {deals.slice(0, 8).map((d) => (
                  <Item
                    key={`d-${d.id}`}
                    icon={Building}
                    value={`${d.project_name} ${d.developer_name} ${d.city} ${d.state}`}
                    onSelect={() => go(`/deals/${d.id}`)}
                    meta={[d.city, d.state].filter(Boolean).join(", ")}
                  >
                    {d.project_name}
                  </Item>
                ))}
              </Command.Group>
            )}

            {developers && developers.length > 0 && (
              <Command.Group heading="Developers" className="mt-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground">
                {developers.slice(0, 6).map((dev) => (
                  <Item
                    key={`dev-${dev.id}`}
                    icon={User}
                    value={`${dev.name} ${dev.contact_email}`}
                    onSelect={() => go(`/developers`)}
                    meta={dev.deal_count === 1 ? "1 deal" : `${dev.deal_count} deals`}
                  >
                    {dev.name}
                  </Item>
                ))}
              </Command.Group>
            )}
          </Command.List>

          <div className="flex items-center gap-4 px-4 h-10 border-t border-border/80 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <kbd className="inline-flex h-4 min-w-4 items-center justify-center rounded border border-border/80 bg-background px-1 font-mono text-[10px]">↑↓</kbd>
              navigate
            </span>
            <span className="flex items-center gap-1.5">
              <kbd className="inline-flex h-4 min-w-4 items-center justify-center rounded border border-border/80 bg-background px-1 font-mono text-[10px]">↵</kbd>
              select
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function Item({
  icon: Icon,
  children,
  onSelect,
  value,
  meta,
}: {
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  onSelect: () => void;
  value?: string;
  meta?: string;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className={cn(
        "group flex items-center gap-3 px-3 h-9 rounded-md text-sm cursor-pointer",
        "data-[selected=true]:bg-muted/70 data-[selected=true]:text-foreground",
        "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1 truncate text-foreground">{children}</span>
      {meta && <span className="text-xs text-muted-foreground truncate">{meta}</span>}
      <ArrowRight className="h-3.5 w-3.5 opacity-0 group-data-[selected=true]:opacity-100 transition-opacity" />
    </Command.Item>
  );
}
