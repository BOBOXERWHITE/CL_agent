import { postJson, requestJson } from "./client";

export type AgentRouterProvider = "llm" | "embedding" | "keyword";

export interface EditableSystemSettings {
  default_tenant_id: string;
  default_customer_id: string;
  chat_top_k: number;
  chat_confidence_threshold: number;
  default_eval_dataset: string;
  agent_router_provider: AgentRouterProvider;
  chat_history_max_turns: number;
}

export interface RuntimeSystemSettings {
  llm_provider: string;
  llm_model_name: string;
  embedding_provider: string;
  embedding_model_name: string;
  embedding_dimension: number;
  vector_store_provider: string;
  auth_enabled: boolean;
}

export interface SystemSettingsResponse {
  editable_settings: EditableSystemSettings;
  runtime_settings: RuntimeSystemSettings;
}

export type UpdateSystemSettingsRequest = EditableSystemSettings;

export async function getSystemSettings(): Promise<SystemSettingsResponse> {
  return requestJson<SystemSettingsResponse>("/api/settings/system");
}

export async function updateSystemSettings(
  payload: UpdateSystemSettingsRequest,
): Promise<SystemSettingsResponse> {
  return postJson<SystemSettingsResponse>("/api/settings/system", payload, {
    method: "PUT",
  });
}
