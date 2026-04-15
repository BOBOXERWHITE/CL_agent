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

export interface RetrievalTrace {
  mode: string;
  prompt_name: string;
  prompt_version: number;
  model_name: string;
  token_usage: {
    input_tokens: number;
    output_tokens: number;
  };
  selected_chunks: RetrievalTraceChunk[];
}

export interface ChatAnswer {
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
  sessionId?: string;
}

export async function askPolicyQuestion(input: AskPolicyQuestionInput): Promise<ChatAnswer> {
  return postJson<ChatAnswer>("/api/chat/ask", {
    question: input.question,
    tenant_id: input.tenantId ?? "default-tenant",
    customer_id: input.customerId ?? "default-customer",
    session_id: input.sessionId ?? null,
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
