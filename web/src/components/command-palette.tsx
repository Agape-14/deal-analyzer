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
import { useCurrentUser } from "@/lib/auth-client";
import type { DealSummary, Developer } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EvidenceViewer, type EvidenceSource } from "./deal-detail/evidence-viewer";

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
  const { isAnalyst } = useCurrentUser();
  const [open, setOpen] = React.useState(false);
  const [deals, setDeals] = React.useState<DealSummary[] | null>(null);
  const [developers, setDevelopers] = React.useState<Developer[] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(false);
  const [retry, reload] = React.useReducer(n => n + 1, 0);
  const [query, setQuery] = React.useState("");
  const [evidence, setEvidence] = React.useState<Array<EvidenceSource & { deal_id: number; project_name: string }>>([]);
  const [evidenceError, setEvidenceError] = React.useState(false);
  const [source, setSource] = React.useState<EvidenceSource | null>(null);

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
    if (!open) return;
    let active = true;
    setLoading(true);
    setError(false);
    Promise.all([
      api.get<DealSummary[]>("/api/deals"),
      api.get<Developer[]>("/api/developers"),
    ])
      .then(([d, dev]) => {
        if (active) { setDeals(d); setDevelopers(dev); }
      })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, retry]);

  React.useEffect(() => {
    setEvidence([]); setEvidenceError(false);
    if (!open || query.trim().length < 2) return;
    let active = true;
    const timer = setTimeout(() => {
      api.get<{ hits: typeof evidence }>(`/api/chat/search?q=${encodeURIComponent(query.trim().slice(0, 200))}`).then(data => { if (active) setEvidence(data.hits); }).catch(() => { if (active) setEvidenceError(true); });
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [open, query]);

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <><Dialog open={open} onOpenChange={setOpen}>
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
              value={query} onValueChange={setQuery}
              placeholder="Search deals, sponsors or source evidence…"
              className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground"
              autoFocus
            />
            <kbd className="hidden sm:inline-flex items-center text-[10px] font-mono text-muted-foreground border border-border/80 rounded px-1.5 py-0.5">
              esc
            </kbd>
          </div>

          <Command.List className="overflow-y-auto py-2 px-1.5">
            {error && <p role="alert" className="px-3 py-2 text-xs text-warning">Records could not be refreshed. {deals ? "Previous results remain below." : ""} <button className="underline" onClick={reload}>Retry search</button></p>}
            {evidenceError && <p role="alert" className="px-3 py-2 text-xs text-warning">Source search unavailable. Try again or open the deal documents.</p>}
            <Command.Empty className="px-3 py-8 text-center text-sm text-muted-foreground">
              {loading ? "Searching…" : "Nothing found."}
            </Command.Empty>
            {evidence.length > 0 && <Command.Group heading="Reported source excerpts · review before use">{evidence.map((hit, i) => <Item key={`source-${hit.document_id}-${i}`} icon={Search} value={`${query} ${hit.project_name} ${hit.excerpt}`} onSelect={() => { setOpen(false); setSource(hit); }} meta={hit.excerpt?.slice(0, 110)}>{hit.project_name} · {hit.document_name}{hit.page ? ` p${hit.page}` : hit.cell ? ` ${hit.cell}` : ""}</Item>)}</Command.Group>}

            <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground">
              {isAnalyst && (
                <>
                  <Item icon={Plus} onSelect={() => go("/?new=1")}>
                    New deal
                  </Item>
                  <Item
                    icon={Plus}
                    onSelect={() => {
                      setOpen(false);
                      // Navigate to portfolio + open the drawer; defer the dispatch
                      // slightly so the drawer exists in the DOM before we fire.
                      router.push("/portfolio");
                      setTimeout(() => {
                        document.dispatchEvent(new CustomEvent("open-new-investment"));
                      }, 120);
                    }}
                  >
                    New investment
                  </Item>
                  <Item
                    icon={Plus}
                    onSelect={() => {
                      setOpen(false);
                      router.push("/developers");
                      setTimeout(() => {
                        document.dispatchEvent(new CustomEvent("open-new-developer"));
                      }, 120);
                    }}
                  >
                    New developer
                  </Item>
                </>
              )}
              <Item icon={LayoutDashboard} onSelect={() => go("/")}>
                Go to deals
              </Item>
              <Item icon={GitCompareArrows} onSelect={() => go("/compare")}>
                Compare deals
              </Item>
              {deals && deals.length >= 2 && (
                <Item
                  icon={GitCompareArrows}
                  onSelect={() => {
                    const top = [...deals].slice(0, Math.min(3, deals.length));
                    go(`/compare?ids=${top.map((d) => d.id).join(",")}&preset=exec`);
                  }}
                >
                  Compare top 3 recent deals
                </Item>
              )}
              <Item icon={Building2} onSelect={() => go("/developers")}>
                View developers
              </Item>
              <Item icon={Wallet} onSelect={() => go("/portfolio")}>
                View portfolio
              </Item>
            </Command.Group>

            {deals && deals.length > 0 && (
              <Command.Group heading="Deals" className="mt-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.12em] [&_[cmdk-group-heading]]:text-muted-foreground">
                {deals.map((d) => (
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
                {developers.map((dev) => (
                  <Item
                    key={`dev-${dev.id}`}
                    icon={User}
                    value={`${dev.name} ${dev.contact_email}`}
                    onSelect={() => go(`/developers/${dev.id}`)}
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
    </Dialog>{source && <EvidenceViewer source={source} autoOpen onClose={() => setSource(null)} />}</>
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
