import { postJson } from "./client";

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
