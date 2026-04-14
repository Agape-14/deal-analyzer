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

/* ------------------------------------------------------------------ */
/*  Deal detail                                                       */
/* ------------------------------------------------------------------ */

export interface DealDocument {
  id: number;
  filename: string;
  doc_type: "offering_memo" | "proforma" | "market_study" | "other" | string;
  page_count: number;
  upload_date: string;
  has_text: boolean;
  extraction_quality?: {
    quality_score: number | null;
    ocr_pages: number;
    empty_pages: number[];
  } | null;
}

/* --- Data integrity primitives (mirror app/services/data_integrity.py) --- */

export interface FieldProvenance {
  source?: "extraction" | "verification" | "manual" | "calculated" | string;
  source_doc_id?: number | null;
  source_doc_name?: string;
  source_page?: number | null;
  extracted_at?: string;
  confidence?: number | null;
  verified_at?: string | null;
  status?: "extracted" | "confirmed" | "wrong" | "unverifiable" | "calculated" | "missing" | "manual" | "stale" | string;
  conflict?: Array<{ doc_id: number; doc_name: string; value: unknown }> | null;
  locked?: boolean;
  verification_source?: string;
  verification_note?: string;
}

export interface DealQualitySummary {
  total_fields: number;
  verified: number;
  extracted: number;
  calculated: number;
  manual: number;
  conflicting: number;
  locked: number;
  wrong: number;
  unverifiable: number;
  last_extracted_at: string | null;
  last_verified_at?: string | null;
  confidence?: number | null;
}

export interface ValidationFlag {
  severity: "red" | "yellow" | "green" | string;
  category: string;
  message: string;
}

export interface ScoreCategory {
  score: number;
  weight: number;
  notes: string;
}

export interface DealScores {
  overall: number;
  returns: ScoreCategory;
  market: ScoreCategory;
  structure: ScoreCategory;
  risk: ScoreCategory;
  financials: ScoreCategory;
  underwriting: ScoreCategory;
  sponsor: ScoreCategory;
}

/** The full metrics blob. All fields optional — the backend fills them
 * progressively via AI extraction. Kept as nullable to match reality. */
export interface DealMetrics {
  deal_structure?: Record<string, unknown>;
  target_returns?: Record<string, unknown>;
  project_details?: Record<string, unknown>;
  financial_projections?: Record<string, unknown>;
  market_location?: Record<string, unknown>;
  risk_assessment?: Record<string, unknown>;
  underwriting_checks?: Record<string, unknown>;
  sponsor_evaluation?: Record<string, unknown>;
  market_research?: Record<string, unknown>;
  validation_flags?: ValidationFlag[];
}

export interface DealDetail extends DealSummary {
  documents: DealDocument[];
  metrics: DealMetrics & {
    _provenance?: Record<string, FieldProvenance>;
    _locks?: Record<string, boolean>;
    _verification?: {
      verified_at?: string;
      confidence?: number | null;
      totals?: Record<string, number>;
    };
    _extraction_history?: Array<{ at: string; changes: string[]; doc_count: number; conflicts: string[] }>;
  };
  scores: Partial<DealScores>;
  quality?: DealQualitySummary;
  lat?: number | null;
  lng?: number | null;
}

/* Cashflow + Waterfall */

export interface CashflowYear {
  year: number;
  gross_revenue: number;
  expenses: number;
  noi: number;
  debt_service: number;
  cash_flow: number;
}

export interface LpCashflowRow {
  year: number;
  type: "investment" | "distribution" | "sale_proceeds" | string;
  amount: number;
  cumulative: number;
}

export interface CashflowResponse {
  project_level: CashflowYear[];
  lp_level: LpCashflowRow[];
  summary: {
    total_operating_cashflow: number;
    exit_value: number;
    exit_equity: number;
    total_return_to_equity: number;
    equity_multiple: number;
    years_modeled: number;
  };
  assumptions?: Record<string, unknown>;
}

/** Per the real backend, a waterfall tier uses `lp_amount` / `gp_amount` and
 * a `total`. `your_amount` is non-null when the user passes `?investment=`. */
export interface WaterfallTier {
  name: string;
  total: number;
  lp_amount: number;
  gp_amount: number;
  lp_pct: number;
  gp_pct: number;
  your_amount: number | null;
}

export interface WaterfallResponse {
  tiers: WaterfallTier[];
  totals: {
    total_distributed: number;
    lp_total: number;
    gp_total: number;
    lp_pct: number;
    gp_pct: number;
    your_total?: number | null;
  };
}

export interface MathCheck {
  name: string;
  status: "pass" | "fail" | "warn" | "info" | string;
  actual?: number | string | null;
  expected?: number | string | null;
  message: string;
}

export interface MathCheckResponse {
  checks: MathCheck[];
  summary: { pass: number; fail: number; warn: number; info: number; total: number };
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Location intelligence                                             */
/* ------------------------------------------------------------------ */

export type PoiCategory =
  | "apartments"
  | "restaurants"
  | "grocery"
  | "transit"
  | "schools"
  | "healthcare"
  | "parks"
  | "employers";

export interface Poi {
  id: string;
  lat: number;
  lng: number;
  name: string;
  category: PoiCategory | string;
  tags: Record<string, string>;
  distance_m: number;
}

export interface HudFmr {
  zip: string;
  year?: number | string;
  metro?: string | null;
  county?: string | null;
  rents: {
    studio?: number | null;
    br1?: number | null;
    br2?: number | null;
    br3?: number | null;
    br4?: number | null;
  };
}

export interface LocationBundle {
  lat: number | null;
  lng: number | null;
  radius_m: number;
  categories: Partial<Record<PoiCategory | string, Poi[]>>;
  fmr: HudFmr | null;
  display_name: string | null;
  fetched_at: number;
  error?: string;
}
