"use client";

import * as React from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import {
  FileText,
  LineChart as LineChartIcon,
  Gauge,
  MessageSquare,
  Waves,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const TABS = [
  { key: "overview", label: "Overview", icon: Gauge },
  { key: "metrics", label: "Metrics", icon: Waves },
  { key: "cashflow", label: "Cashflow", icon: LineChartIcon },
  { key: "documents", label: "Documents", icon: FileText },
  { key: "chat", label: "Analyst", icon: MessageSquare },
] as const;

export type DealTabKey = (typeof TABS)[number]["key"];

/**
 * Tab shell that drives the deal-detail view via `?tab=...` in the URL.
 * Clicking a tab does a shallow `router.replace` — no re-fetch, just a
 * URL change that keeps the state bookmarkable and back-button friendly.
 */
export function DealTabs({
  overview,
  metrics,
  cashflow,
  documents,
  chat,
  defaultTab = "overview",
}: {
  overview: React.ReactNode;
  metrics: React.ReactNode;
  cashflow: React.ReactNode;
  documents: React.ReactNode;
  chat: React.ReactNode;
  defaultTab?: DealTabKey;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlTab = (searchParams?.get("tab") as DealTabKey) || defaultTab;
  const [active, setActive] = React.useState<DealTabKey>(urlTab);

  // Keep local state in sync with URL (e.g. back button)
  React.useEffect(() => {
    if (urlTab && urlTab !== active) setActive(urlTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlTab]);

  function onValueChange(v: string) {
    const next = v as DealTabKey;
    setActive(next);
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  return (
    <Tabs value={active} onValueChange={onValueChange} className="w-full">
      <TabsList>
        {TABS.map((t) => (
          <TabsTrigger key={t.key} value={t.key} indicatorId="deal-tabs-underline">
            <t.icon className="h-3.5 w-3.5" />
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="overview">{overview}</TabsContent>
      <TabsContent value="metrics">{metrics}</TabsContent>
      <TabsContent value="cashflow">{cashflow}</TabsContent>
      <TabsContent value="documents">{documents}</TabsContent>
      <TabsContent value="chat">{chat}</TabsContent>
    </Tabs>
  );
}
