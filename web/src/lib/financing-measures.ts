export const financingKinds = {
  draw: "Construction loan draw",
  peak_balance: "Modeled peak construction loan balance",
  modeled_payoff: "Modeled construction debt at payoff",
  lender_commitment: "Construction lender commitment",
} as const;

export type FinancingKind = keyof typeof financingKinds;

export type FinancingCitation = {
  source_doc_id: number;
  source_doc_name?: string;
  source_page?: number;
  source_sheet?: string;
  source_cell?: string;
  source_excerpt: string;
};

export type FinancingMeasure = {
  kind: FinancingKind;
  label: string;
  amount: number;
  currency: "USD";
  debt_phase: "construction";
  note: string;
  state: "checked" | "stale";
  evidence: Array<{
    document_id: number;
    document_name: string;
    content_hash: string;
    page?: number | null;
    sheet?: string | null;
    cell?: string | null;
    excerpt?: string;
  }>;
  citation: FinancingCitation;
};

export type FinancingAnalysis = {
  debt_amount_kind: FinancingKind | null;
  debt_amount_label: string;
  debt_amount_currency: "USD" | null;
  measures: FinancingMeasure[];
};
