"use client";

import { MetricsSection } from "@/components/deal-detail/metrics-section";
import type { DealDetail } from "@/lib/types";

const SECTIONS: Array<{
  key: keyof NonNullable<DealDetail["metrics"]>;
  title: string;
  description: string;
}> = [
  { key: "deal_structure", title: "Deal structure", description: "Capitalization, leverage, fees, and waterfall mechanics." },
  { key: "target_returns", title: "Target returns", description: "Projected IRR, multiple, cash-on-cash, yield." },
  { key: "project_details", title: "Project details", description: "Units, square footage, construction, timing." },
  { key: "construction_costs", title: "Construction costs", description: "Total, hard, soft, land costs — total and per unit. Key for deal comparison." },
  { key: "financial_projections", title: "Financial projections", description: "NOI, cap rates, rent and expense assumptions." },
  { key: "market_location", title: "Market & location", description: "Geography, submarket, demographics, drivers." },
  { key: "underwriting_checks", title: "Underwriting", description: "BEO, DSCR, YoC, sensitivities." },
  { key: "risk_assessment", title: "Risk assessment", description: "Category-by-category risk scores (1–10)." },
  { key: "sponsor_evaluation", title: "Sponsor evaluation", description: "Track record, alignment, team." },
];

export function MetricsTab({ deal }: { deal: DealDetail }) {
  const provenance = deal.metrics?._provenance;
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {SECTIONS.map((s) => (
        <MetricsSection
          key={s.key}
          title={s.title}
          description={s.description}
          sectionKey={String(s.key)}
          data={deal.metrics?.[s.key] as Record<string, unknown> | undefined}
          provenance={provenance}
          dealId={deal.id}
        />
      ))}
    </div>
  );
}
