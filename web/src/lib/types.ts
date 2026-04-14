/**
 * Domain types. These mirror the FastAPI response shapes.
 *
 * Kept narrow on purpose — we only type the fields we read. When the API
 * gets a breaking change, fix types here first, then TypeScript will point
 * to every affected render site.
 */

export type DealStatus = "reviewing" | "interested" | "passed" | "committed" | "closed";

export interface DealSummary {
  id: number;
  developer_id: number | null;
  developer_name: string;
  project_name: string;
  location: string;
  city: string;
  state: string;
  property_type: string;
  status: DealStatus;
  metrics: Record<string, unknown>;
  scores: Record<string, unknown>;
  overall_score: number | null;
  target_irr: number | null;
  target_equity_multiple: number | null;
  minimum_investment: number | null;
  notes: string;
  created_at: string;
}

export interface Developer {
  id: number;
  name: string;
  contact_name: string;
  contact_email: string;
  phone: string;
  track_record: string;
  notes: string;
  deal_count: number;
  created_at: string | null;
}

export interface Investment {
  id: number;
  deal_id: number | null;
  deal_name: string | null;
  project_name: string;
  sponsor_name: string;
  investment_date: string | null;
  amount_invested: number;
  shares: number;
  investment_class: string;
  preferred_return: number | null;
  projected_irr: number | null;
  projected_equity_multiple: number | null;
  hold_period_years: number | null;
  status: "active" | "exited" | "defaulted" | "pending";
  exit_date: string | null;
  exit_amount: number | null;
  notes: string;
  created_at: string | null;
  total_distributions: number;
  total_returned: number;
  actual_multiple: number;
  actual_coc: number;
  net_profit: number;
  distributions: Distribution[];
}

export interface Distribution {
  id: number;
  date: string | null;
  amount: number;
  dist_type: string;
  period: string;
  notes: string;
}

export interface PortfolioSummary {
  total_invested: number;
  total_distributions: number;
  total_exit_proceeds: number;
  total_returned: number;
  net_profit: number;
  overall_multiple: number;
  active_investments: number;
  exited_investments: number;
  total_investments: number;
}

export interface InvestmentPerformance {
  investment_id: number;
  invested: number;
  total_distributions: number;
  exit_amount: number;
  total_returned: number;
  net_profit: number;
  multiple: number;
  dpi: number;
  tvpi: number;
  irr: number | null;
  years_held: number | null;
  projected_irr: number | null;
  projected_multiple: number | null;
  irr_vs_projected: number | null;
  cashflow_count: number;
  cumulative_timeseries: Array<{
    date: string;
    cumulative_distributions: number;
    cumulative_multiple: number;
    is_exit?: boolean;
  }>;
}

export interface PortfolioAnalytics {
  summary: PortfolioSummary & { overall_irr_pct: number | null; investment_count: number };
  per_investment: InvestmentPerformance[];
  by_status: Array<{ name: string; count: number; invested: number; returned: number; share_pct: number; multiple: number }>;
  by_sponsor: Array<{ name: string; count: number; invested: number; returned: number; share_pct: number; multiple: number }>;
  timeseries: Array<{ date: string; cumulative_invested: number; cumulative_returned: number; net_position: number; multiple: number }>;
  top_performers: InvestmentPerformance[];
  bottom_performers: InvestmentPerformance[];
}
