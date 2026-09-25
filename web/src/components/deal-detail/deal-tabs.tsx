"use client";

import * as React from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import {
  FileText,
  LineChart as LineChartIcon,
  Gauge,
  MessageSquare,
  Waves,
  MapPin,
  CircleHelp,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useCurrentUser } from "@/lib/auth-client";

const TABS = [
  { key: "overview", label: "Summary", icon: Gauge },
  { key: "questions", label: "Questions", icon: CircleHelp },
  { key: "documents", label: "Documents", icon: FileText },
  { key: "analysis", label: "Analysis", icon: Waves },
  { key: "chat", label: "Analyst", icon: MessageSquare },
] as const;

export type DealTabKey = (typeof TABS)[number]["key"] | "metrics" | "cashflow" | "location" | "audit";
const ANALYSIS_TABS = ["metrics", "cashflow", "location", "audit"];

/**
 * Tab shell that drives the deal-detail view via `?tab=...` in the URL.
 * Clicking a tab does a shallow `router.replace` — no re-fetch, just a
 * URL change that keeps the state bookmarkable and back-button friendly.
 */
export function DealTabs({
  overview,
  questions,
  audit,
  metrics,
  cashflow,
  location,
  documents,
  chat,
  defaultTab = "overview",
}: {
  overview: React.ReactNode;
  questions: React.ReactNode;
  audit: React.ReactNode;
  metrics: React.ReactNode;
  cashflow: React.ReactNode;
  location: React.ReactNode;
  documents: React.ReactNode;
  chat: React.ReactNode;
  defaultTab?: DealTabKey;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isAnalyst, loading } = useCurrentUser();
  const visibleTabs = React.useMemo(
    () => (loading || !isAnalyst ? TABS.filter((tab) => tab.key !== "chat") : [...TABS]),
    [isAnalyst, loading],
  );
  const urlTab = (searchParams?.get("tab") as DealTabKey) || defaultTab;
  const [active, setActive] = React.useState<DealTabKey>(urlTab);
  const resolvedActive = ANALYSIS_TABS.includes(active) ? "analysis" : visibleTabs.some((tab) => tab.key === active) ? active : "overview";

  // Keep local state in sync with URL (e.g. back button)
  React.useEffect(() => {
    if (urlTab && urlTab !== active) setActive(urlTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlTab]);

  React.useEffect(() => {
    if (visibleTabs.some((tab) => tab.key === active) || ANALYSIS_TABS.includes(active)) return;
    setActive("overview");
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", "overview");
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [active, pathname, router, searchParams, visibleTabs]);

  function onValueChange(v: string) {
    const next = v as DealTabKey;
    setActive(next);
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  return (
    <Tabs value={resolvedActive} onValueChange={onValueChange} className="w-full">
      <TabsList className="overflow-x-auto w-full">
        {visibleTabs.map((t) => (
          <TabsTrigger
            key={t.key}
            value={t.key}
            indicatorId="deal-tabs-underline"
            className="shrink-0"
          >
            <t.icon className="h-3.5 w-3.5" />
            <span>{t.label}</span>
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="overview">{overview}</TabsContent>
      <TabsContent value="questions">{questions}</TabsContent>
      <TabsContent value="analysis">
        <Tabs value={ANALYSIS_TABS.includes(active) ? active : "metrics"} onValueChange={onValueChange}>
          <TabsList className="mb-5 w-full overflow-x-auto">
            <TabsTrigger value="metrics">Reported metrics</TabsTrigger>
            <TabsTrigger value="cashflow">Projections</TabsTrigger>
            <TabsTrigger value="location">Location</TabsTrigger>
            <TabsTrigger value="audit">Evidence and history</TabsTrigger>
          </TabsList>
          <TabsContent value="metrics"><p className="mb-4 text-sm text-muted-foreground">Source-reported values and optional context. Use Summary for accepted facts.</p>{metrics}</TabsContent>
          <TabsContent value="cashflow">{cashflow}</TabsContent>
          <TabsContent value="location">{location}</TabsContent>
          <TabsContent value="audit">{audit}</TabsContent>
        </Tabs>
      </TabsContent>
      <TabsContent value="documents">{documents}</TabsContent>
      <TabsContent value="chat">{chat}</TabsContent>
    </Tabs>
  );
}
