import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import App from "../../src/app/App";

vi.mock("../../src/api/knowledge", () => ({
  listKnowledgeJobs: vi.fn().mockResolvedValue([]),
  uploadKnowledgeDocument: vi.fn(),
  rebuildKnowledgeIndex: vi.fn(),
  deleteKnowledgeDocument: vi.fn(),
  checkKnowledgeEmbeddingReadiness: vi.fn().mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "当前使用本地 deterministic embedding，无需额外连通性检查。",
    endpoint: null,
  }),
  runKnowledgeEmbeddingSmokeTest: vi.fn().mockResolvedValue({
    provider: "deterministic",
    model_name: "deterministic-hash-embedding",
    configured: true,
    available: true,
    status: "ready",
    message: "Embedding 烟雾测试通过。",
    endpoint: null,
    sample_text: "北京酒店报销上限",
    latency_ms: 12.5,
    vector_dimension: 16,
  }),
}));

vi.mock("../../src/api/chat", () => ({
  askPolicyQuestion: vi.fn(),
}));

vi.mock("../../src/api/prompts", () => ({
  createPromptTemplate: vi.fn(),
  listPromptTemplates: vi.fn().mockResolvedValue([]),
  activatePromptTemplate: vi.fn(),
}));

vi.mock("../../src/api/evals", () => ({
  listEvalRuns: vi.fn().mockResolvedValue([]),
  triggerEvalRun: vi.fn(),
}));

vi.mock("../../src/api/agents", () => ({
  listAgentRuns: vi.fn().mockResolvedValue([]),
  createAgentRun: vi.fn(),
}));

vi.mock("../../src/api/reviews", () => ({
  listReviewCases: vi.fn().mockResolvedValue([]),
}));

vi.mock("../../src/api/monitoring", () => ({
  getMonitoringOverview: vi.fn().mockResolvedValue({
    knowledge_summary: {
      document_total: 4,
      completed_total: 3,
      failed_total: 1,
      pending_reindex_total: 2,
    },
    chat_summary: {
      session_total: 5,
      message_total: 9,
    },
    review_summary: {
      open_total: 2,
    },
    agent_summary: {
      last_24h_total: 3,
    },
    eval_summary: {
      last_24h_total: 1,
    },
    request_summary: {
      last_hour_total: 12,
      last_hour_error_total: 1,
      last_hour_p95_latency_ms: 45,
    },
    recent_activity: {
      recent_failed_requests: [],
      recent_eval_runs: [],
      recent_agent_runs: [],
    },
  }),
}));

vi.mock("../../src/api/logs", () => ({
  listRuntimeLogs: vi.fn().mockResolvedValue([]),
  getRuntimeLogDetail: vi.fn(),
}));

vi.mock("../../src/api/settings", () => ({
  getSystemSettings: vi.fn().mockResolvedValue({
    editable_settings: {
      default_tenant_id: "演示租户",
      default_customer_id: "演示客户",
      chat_top_k: 3,
      chat_confidence_threshold: 0.2,
      default_eval_dataset: "zh-policy-smoke",
    },
    runtime_settings: {
      llm_provider: "deterministic",
      llm_model_name: "deterministic-policy-client",
      embedding_provider: "deterministic",
      embedding_model_name: "deterministic-hash-embedding",
      embedding_dimension: 16,
      vector_store_provider: "milvus",
      auth_enabled: false,
    },
  }),
  updateSystemSettings: vi.fn(),
}));

test("renders tabbed admin shell and switches between workspaces", async () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "差旅智能运营后台" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "知识库管理" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "监控面板" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "运行日志" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "系统设置" })).toBeInTheDocument();

  await screen.findByRole("heading", { name: "知识库管理" });
  expect(screen.queryByRole("heading", { name: "监控面板" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("tab", { name: "监控面板" }));

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "监控面板" })).toBeInTheDocument();
  });
});
