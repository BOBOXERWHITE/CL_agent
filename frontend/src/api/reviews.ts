import { requestJson } from "./client";

export interface RuleHit {
  rule_code: string;
  decision: string;
  threshold_amount: number;
  actual_amount: number;
  reason: string;
}

export interface RuleResult {
  decision: string;
  reason: string;
  suggested_action: string;
  rule_hits: RuleHit[];
}

export interface ReviewCase {
  id: string;
  source: string;
  tenant_id: string;
  customer_id: string;
  status: string;
  confidence: number;
  reason: string;
  suggested_action: string;
  payload: Record<string, unknown>;
  rule_result: RuleResult | Record<string, never>;
  created_at: string;
  updated_at: string;
}

interface ReviewCaseListResponse {
  items: ReviewCase[];
}

export async function listReviewCases(): Promise<ReviewCase[]> {
  const response = await requestJson<ReviewCaseListResponse>("/api/reviews/queue");
  return response.items;
}
