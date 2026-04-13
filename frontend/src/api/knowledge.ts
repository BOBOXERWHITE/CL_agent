import { createFormHeaders, requestJson } from "./client";

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
  stored_embedding_profile?: KnowledgeEmbeddingProfile | null;
  current_embedding_profile?: KnowledgeEmbeddingProfile | null;
  requires_reindex?: boolean;
}

export interface KnowledgeEmbeddingProfile {
  provider: string;
  model_name: string;
  dimension: number;
  profile_key: string;
}

export interface KnowledgeEmbeddingReadiness {
  provider: string;
  model_name: string;
  configured: boolean;
  available: boolean;
  status: string;
  message: string;
  endpoint?: string | null;
}

export interface KnowledgeEmbeddingSmokeTest {
  provider: string;
  model_name: string;
  configured: boolean;
  available: boolean;
  status: string;
  message: string;
  endpoint?: string | null;
  sample_text: string;
  latency_ms: number;
  vector_dimension: number;
}

export interface KnowledgeRebuildResult {
  scope: "all" | "document" | "stale";
  document_count: number;
  chunk_count: number;
  document_ids: string[];
}

export interface KnowledgeDeleteResult {
  document_id: string;
  filename: string;
  chunk_count: number;
}

interface RebuildKnowledgeIndexInput {
  documentId?: string;
  staleOnly?: boolean;
}

interface UploadKnowledgeDocumentInput {
  tenantId: string;
  customerId: string;
  file: File;
}

interface KnowledgeJobListResponse {
  items: KnowledgeJob[];
}

export async function listKnowledgeJobs(): Promise<KnowledgeJob[]> {
  const response = await requestJson<KnowledgeJobListResponse>("/api/knowledge/jobs");
  return response.items;
}

export async function checkKnowledgeEmbeddingReadiness(): Promise<KnowledgeEmbeddingReadiness> {
  return requestJson<KnowledgeEmbeddingReadiness>("/api/knowledge/embedding-readiness");
}

export async function runKnowledgeEmbeddingSmokeTest(): Promise<KnowledgeEmbeddingSmokeTest> {
  return requestJson<KnowledgeEmbeddingSmokeTest>("/api/knowledge/embedding-smoke-test", {
    method: "POST",
  });
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
    headers: createFormHeaders(),
    body: formData,
  });
}

export async function rebuildKnowledgeIndex(
  input: RebuildKnowledgeIndexInput,
): Promise<KnowledgeRebuildResult> {
  return requestJson<KnowledgeRebuildResult>("/api/knowledge/reindex", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: input.documentId,
      stale_only: input.staleOnly ?? false,
    }),
  });
}

export async function deleteKnowledgeDocument(documentId: string): Promise<KnowledgeDeleteResult> {
  return requestJson<KnowledgeDeleteResult>(`/api/knowledge/documents/${documentId}`, {
    method: "DELETE",
  });
}
