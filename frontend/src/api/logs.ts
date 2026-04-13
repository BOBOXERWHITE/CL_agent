import { requestJson } from "./client";

export interface RuntimeLogItem {
  id: string;
  request_id: string;
  method: string;
  path: string;
  status_code: number;
  latency_ms: number;
  tenant_id?: string | null;
  customer_id?: string | null;
  session_id?: string | null;
  user_role?: string | null;
  model_name?: string | null;
  token_usage_json: Record<string, number>;
  error_message?: string | null;
  created_at: string;
}

export interface RuntimeLogDetail extends RuntimeLogItem {}

interface RuntimeLogListResponse {
  items: RuntimeLogItem[];
}

export interface RuntimeLogFilters {
  path?: string;
  statusCode?: string;
  requestId?: string;
  tenantId?: string;
  sessionId?: string;
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
}

export async function listRuntimeLogs(filters: RuntimeLogFilters = {}): Promise<RuntimeLogItem[]> {
  const params = new URLSearchParams();
  if (filters.path) {
    params.set("path", filters.path);
  }
  if (filters.statusCode) {
    params.set("status_code", filters.statusCode);
  }
  if (filters.requestId) {
    params.set("request_id", filters.requestId);
  }
  if (filters.tenantId) {
    params.set("tenant_id", filters.tenantId);
  }
  if (filters.sessionId) {
    params.set("session_id", filters.sessionId);
  }
  if (filters.dateFrom) {
    params.set("date_from", filters.dateFrom);
  }
  if (filters.dateTo) {
    params.set("date_to", filters.dateTo);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await requestJson<RuntimeLogListResponse>(`/api/logs/runtime${suffix}`);
  return response.items;
}

export async function getRuntimeLogDetail(runtimeLogId: string): Promise<RuntimeLogDetail> {
  return requestJson<RuntimeLogDetail>(`/api/logs/runtime/${runtimeLogId}`);
}
