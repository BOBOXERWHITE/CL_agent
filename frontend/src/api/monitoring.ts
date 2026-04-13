import { requestJson } from "./client";

export interface MonitoringOverview {
  knowledge_summary: {
    document_total: number;
    completed_total: number;
    failed_total: number;
    pending_reindex_total: number;
  };
  chat_summary: {
    session_total: number;
    message_total: number;
  };
  review_summary: {
    open_total: number;
  };
  agent_summary: {
    last_24h_total: number;
  };
  eval_summary: {
    last_24h_total: number;
  };
  request_summary: {
    last_hour_total: number;
    last_hour_error_total: number;
    last_hour_p95_latency_ms: number;
  };
  recent_activity: {
    recent_failed_requests: {
      id: string;
      request_id: string;
      path: string;
      status_code: number;
      created_at: string;
      error_message?: string | null;
    }[];
    recent_eval_runs: {
      id: string;
      dataset_name: string;
      status: string;
      created_at: string;
    }[];
    recent_agent_runs: {
      id: string;
      agent_name: string;
      status: string;
      created_at: string;
    }[];
  };
}

export async function getMonitoringOverview(): Promise<MonitoringOverview> {
  return requestJson<MonitoringOverview>("/api/monitoring/overview");
}
