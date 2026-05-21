import { postJson, requestJson } from "./client";

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_title: string;
  snippet: string;
  score: number;
}

export interface RetrievalTraceChunk {
  chunk_id: string;
  document_id: string;
  document_title: string;
  score: number;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface RetrievalTraceRouter {
  domain?: string;
  specialist?: string;
  confidence?: number;
  fallback_reason?: string | null;
  planned_domains?: string[];
}

export interface RetrievalTraceInterrupt {
  kind?: string;
  reason?: string;
  queue_name?: string;
  anomaly_code?: string;
  missing_dimensions?: string[];
  allowed_decisions?: string[];
}

export interface RetrievalTraceCheckpoint {
  id: string;
  checkpoint_type: string;
  status: string;
  created_at: string;
}

export interface RetrievalTraceTimelineNode {
  node_name: string;
  status: string;
  detail?: string;
  timestamp?: string;
}

export interface RetrievalTraceToolCall {
  tool_name: string;
  status: string;
  latency_ms?: number;
}

export interface RetrievalTraceEvent {
  category: string;
  name: string;
  status: string;
  detail: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export interface RetrievalTraceCoverage {
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

export interface RetrievalGuardrailEvent {
  decision?: string;
  reason?: string;
  missing_dimensions?: string[];
  thread_id?: string;
  [key: string]: unknown;
}

export interface RetrievalTraceCragRound {
  round_index: number;
  sufficiency_score: number;
  covered_aspects?: string[];
  missing_aspects?: string[];
  suggested_queries?: string[];
  triggered_re_retrieval?: boolean;
  new_chunks_added?: number;
  reasoning?: string;
}

export interface RetrievalTrace {
  mode?: string;
  prompt_name?: string;
  prompt_version?: number;
  model_name?: string;
  token_usage?: TokenUsage;
  selected_chunks?: RetrievalTraceChunk[];
  original_query?: string | null;
  expanded_query?: string | null;
  rewrite_rules?: string[];
  candidate_count?: number;
  crag_rounds?: RetrievalTraceCragRound[];
  router?: RetrievalTraceRouter;
  coverage?: RetrievalTraceCoverage;
  guardrail_events?: RetrievalGuardrailEvent[];
  thread_id?: string;
  specialist_plan?: string[];
  agent_name?: string;
  route_name?: string;
  thread_status?: string;
  queue_name?: string;
  pending_interrupt?: RetrievalTraceInterrupt | null;
  latest_checkpoint?: RetrievalTraceCheckpoint | null;
  timeline_nodes?: RetrievalTraceTimelineNode[];
  tool_calls?: RetrievalTraceToolCall[];
  trace_events?: RetrievalTraceEvent[];
}

export interface ChatAnswer {
  thread_id: string;
  session_id: string;
  answer: string;
  confidence: number;
  citations: Citation[];
  retrieval_trace?: RetrievalTrace | null;
}

export interface LlmReadiness {
  provider: string;
  model_name: string;
  configured: boolean;
  available: boolean;
  status: string;
  message: string;
  endpoint?: string | null;
}

export interface LlmSmokeTest {
  provider: string;
  model_name: string;
  configured: boolean;
  available: boolean;
  status: string;
  message: string;
  sample_question: string;
  sample_evidence: string;
  answer_preview: string;
  latency_ms: number;
  token_usage: {
    input_tokens: number;
    output_tokens: number;
  };
  endpoint?: string | null;
}

interface AskPolicyQuestionInput {
  question: string;
  tenantId?: string;
  customerId?: string;
  threadId?: string;
  sessionId?: string;
}

export async function askPolicyQuestion(input: AskPolicyQuestionInput): Promise<ChatAnswer> {
  const threadId = input.threadId ?? input.sessionId ?? null;
  return postJson<ChatAnswer>("/api/chat/ask", {
    question: input.question,
    tenant_id: input.tenantId ?? "default-tenant",
    customer_id: input.customerId ?? "default-customer",
    thread_id: threadId,
    session_id: threadId,
  });
}

export async function getLlmReadiness(): Promise<LlmReadiness> {
  return requestJson<LlmReadiness>("/api/chat/llm-readiness");
}

export async function runLlmSmokeTest(): Promise<LlmSmokeTest> {
  return requestJson<LlmSmokeTest>("/api/chat/llm-smoke-test", {
    method: "POST",
  });
}
