import type { RetrievalTrace } from "./chat";

import { postJson, requestJson } from "./client";

export interface AgentTimelineStep {
  node_name: string;
  status: string;
  detail: string;
  timestamp: string;
}

export interface AgentToolCall {
  tool_name: string;
  status: string;
  latency_ms: number;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown>;
}

export interface AgentCoverage {
  required_dimensions?: string[];
  covered_dimensions?: string[];
  coverage_ratio?: number;
  per_domain?: Record<
    string,
    {
      required_dimensions?: string[];
      covered_dimensions?: string[];
      coverage_ratio?: number;
    }
  >;
}

export interface AgentProfileReport {
  domain?: string;
  label?: string;
  primary_answer?: string;
  missing_dimensions?: string[];
  coverage?: AgentCoverage;
}

export interface AgentInterrupt {
  kind?: string;
  reason?: string;
  queue_name?: string;
  anomaly_code?: string;
  missing_dimensions?: string[];
  allowed_decisions?: string[];
}

export interface AgentCheckpoint {
  id: string;
  checkpoint_type: string;
  status: string;
  created_at: string;
}

export interface AgentResolution {
  decision?: string;
  note?: string;
  resolved_by?: string;
  resolved_at?: string;
}

export interface AgentRunOutput {
  answer?: string;
  reason?: string;
  queue_name?: string;
  review_case_id?: string;
  specialist?: string;
  rule_result?: Record<string, unknown>;
  retrieval_trace?: RetrievalTrace | null;
  orchestration_trace?: RetrievalTrace | null;
  coverage?: AgentCoverage;
  missing_dimensions?: string[];
  specialist_plan?: string[];
  profile_reports?: AgentProfileReport[];
  guardrail_events?: Array<Record<string, unknown>>;
  interrupt?: AgentInterrupt | null;
  resolution?: AgentResolution;
  [key: string]: unknown;
}

export interface AgentRun {
  id: string;
  thread_id: string;
  agent_name: string;
  route_name: string;
  status: string;
  confidence: number;
  requires_human_review: boolean;
  thread_status?: string | null;
  pending_interrupt?: AgentInterrupt | null;
  latest_checkpoint?: AgentCheckpoint | null;
  output: AgentRunOutput;
  timeline: AgentTimelineStep[];
  tool_calls: AgentToolCall[];
  created_at: string;
  updated_at: string;
}

interface AgentRunListResponse {
  items: AgentRun[];
}

interface CreateAgentRunInput {
  question: string;
  tenantId?: string;
  customerId?: string;
  threadId?: string;
  ticket?: {
    ticket_id: string;
    expense_type: string;
    city: string;
    amount: number;
    status: string;
  };
}

export interface AgentRunResumeInput {
  decision: "approve" | "edit" | "reject";
  note?: string;
  editedAnswer?: string;
}

export async function listAgentRuns(): Promise<AgentRun[]> {
  const response = await requestJson<AgentRunListResponse>("/api/agents/runs");
  return response.items;
}

export async function createAgentRun(input: CreateAgentRunInput): Promise<AgentRun> {
  return postJson<AgentRun>("/api/agents/runs", {
    question: input.question,
    tenant_id: input.tenantId ?? "default-tenant",
    customer_id: input.customerId ?? "default-customer",
    thread_id: input.threadId ?? null,
    ticket: input.ticket ?? null,
  });
}

export async function resumeAgentRun(runId: string, input: AgentRunResumeInput): Promise<AgentRun> {
  return postJson<AgentRun>(`/api/agents/runs/${runId}/resume`, {
    decision: input.decision,
    note: input.note ?? "",
    edited_answer: input.editedAnswer ?? null,
  });
}
