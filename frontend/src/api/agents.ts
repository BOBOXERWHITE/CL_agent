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

export interface AgentRun {
  id: string;
  agent_name: string;
  route_name: string;
  status: string;
  confidence: number;
  requires_human_review: boolean;
  output: Record<string, unknown>;
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
  ticket?: {
    ticket_id: string;
    expense_type: string;
    city: string;
    amount: number;
    status: string;
  };
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
    ticket: input.ticket ?? null,
  });
}
