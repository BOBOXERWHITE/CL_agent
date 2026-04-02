export interface KnowledgeUploadAccepted {
  job_id: string;
  document_id: string;
  status: string;
}

export interface KnowledgeJob {
  job_id: string;
  document_id: string;
  filename: string;
  status: string;
  chunk_count: number;
  tenant_id: string;
  customer_id: string;
  created_at: string;
  updated_at: string;
}

interface KnowledgeJobListResponse {
  items: KnowledgeJob[];
}

interface UploadKnowledgeDocumentInput {
  tenantId: string;
  customerId: string;
  file: File;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new Error(`request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function listKnowledgeJobs(): Promise<KnowledgeJob[]> {
  const response = await requestJson<KnowledgeJobListResponse>("/api/knowledge/jobs");
  return response.items;
}

export async function uploadKnowledgeDocument(
  input: UploadKnowledgeDocumentInput,
): Promise<KnowledgeUploadAccepted> {
  const formData = new FormData();
  formData.append("tenant_id", input.tenantId);
  formData.append("customer_id", input.customerId);
  formData.append("file", input.file);

  return requestJson<KnowledgeUploadAccepted>("/api/knowledge/upload", {
    method: "POST",
    body: formData,
  });
}
