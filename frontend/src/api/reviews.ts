import { requestJson } from "./client";
import type { RetrievalTraceEvent } from "./chat";

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

export interface ReviewInterrupt {
  kind?: string;
  reason?: string;
  queue_name?: string;
  anomaly_code?: string;
  allowed_decisions?: string[];
}

export interface ReviewCheckpoint {
  id: string;
  checkpoint_type: string;
  status: string;
  created_at: string;
}

export interface ReviewCase {
  id: string;
  source: string;
  tenant_id: string;
  customer_id: string;
  agent_run_id?: string | null;
  thread_id?: string | null;
  status: string;
  confidence: number;
  reason: string;
  suggested_action: string;
  payload: Record<string, unknown>;
  rule_result: RuleResult | Record<string, never>;
  pending_interrupt?: ReviewInterrupt | null;
  latest_checkpoint?: ReviewCheckpoint | null;
  trace_events?: RetrievalTraceEvent[];
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
