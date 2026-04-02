export interface Citation {
  chunk_id: string;
  document_id: string;
  document_title: string;
  snippet: string;
  score: number;
}

export interface ChatAnswer {
  session_id: string;
  answer: string;
  confidence: number;
  citations: Citation[];
}

interface AskPolicyQuestionInput {
  question: string;
  tenantId?: string;
  customerId?: string;
  sessionId?: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function askPolicyQuestion(input: AskPolicyQuestionInput): Promise<ChatAnswer> {
  const response = await fetch(`${API_BASE_URL}/api/chat/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      question: input.question,
      tenant_id: input.tenantId ?? "default-tenant",
      customer_id: input.customerId ?? "default-customer",
      session_id: input.sessionId ?? null,
    }),
  });

  if (!response.ok) {
    throw new Error(`request failed with status ${response.status}`);
  }

  return (await response.json()) as ChatAnswer;
}
