export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: Record<string, any> | null;
}

export type RunStatus = "EXECUTED" | "ERROR";
export type RiskVerdict = "APPROVED" | "REJECTED_AT_LIMIT";
export type Action = "BUY" | "HOLD" | "SELL";
export type Side = "BUY" | "SELL";
export type TradeStatus = "EXECUTED" | "CANCELLED";

export interface Recommendation {
  id: number;
  run_id: string;
  run_date: string;
  ticker: string;
  reasoning: string;
  sentiment_score: number;
  action: Action;
  price_at_analysis: number;
  created_at: string;
}

export interface Trade {
  id: number;
  run_id: string;
  run_date: string;
  ticker: string;
  side: Side;
  price: number;
  status: TradeStatus;
  executed_at: string;
  cancelled_at?: string | null;
  cancellable: boolean;
}

export interface RiskIssue {
  ticker: string;
  issue: string;
}

export interface RiskReview {
  approved: boolean;
  issues: RiskIssue[];
  overall_notes: string;
}

export interface Run {
  id: string;
  run_date: string;
  status: RunStatus;
  risk_verdict?: RiskVerdict | null;
  risk_rounds: number;
  evidence_rounds: number;
  error_message?: string | null;
  created_at: string;
  recommendation_count: number;
  trade_count: number;
}

export interface RunDetail extends Run {
  risk_review?: RiskReview | null;
  recommendations: Recommendation[];
  trades: Trade[];
}
